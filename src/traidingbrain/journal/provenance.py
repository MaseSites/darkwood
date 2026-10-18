"""Welche Entscheidung zu welchem Fill gehört -- nachweisbar, nicht ungefähr.

**Der Anlass steht im Audit.** Am 11.10.2026 wurde versucht, Fills ihren
Entscheidungen über *ungefähren* Preis und Zeitpunkt zuzuordnen. Die Zuordnung
war fuzzy, und sie hat 78 widersprüchliche Signaturen verdeckt; erst ein exakter
Verbund über `proposal_id` brachte 98,91 % und machte die Widersprüche sichtbar.
Ein unscharfer Schlüssel ist kein Schlüssel.

**Was `decision_id` ist.** Ein Hash über den *Inhalt* der Entscheidung -- Lauf,
Symbol, Zeitpunkt, Richtung, Einstieg, Stop, Ziel, Setup, Zeitebene. Daraus
folgen drei Eigenschaften, die ein laufende Nummer nicht hat:

* Dieselbe Entscheidung in zwei Läufen bekommt denselben Schlüssel, also ist
  ein Replay als Replay erkennbar.
* Zwei verschiedene Entscheidungen können nicht denselben Schlüssel bekommen,
  also kann ein Fill nicht an der falschen hängen.
* Der Schlüssel ist **abgeleitet und nicht übergeben**. Eine übergebene ID ist
  eine Stelle, an der zwei Dinge auseinanderlaufen können.

**Warum ein Fill ohne Decision verboten ist.** Am 17.10.2026 gemessen: ein
lebender Trade in `BTCUSDT` gehörte zu keinem Konto, dem Kontobuch fehlten 55,05
USDT, und die Waise hat die Vorwärtsstichprobe auf drei Wegen verunreinigt. Eine
Waise ist nicht „eine Zeile ohne Zusatzangabe" -- sie ist eine Zeile, die in
jeder Auswertung mitläuft und in keiner erklärbar ist. Darum bricht
`ProvenanceLedger.record` ab, statt zu warnen.

**Fliesskomma im Hash.** Die Preise gehen als `float.hex()` ein, nicht als
Dezimaltext. `f"{x:.8f}"` würde zwei verschiedene Preise auf denselben
Schlüssel abbilden, und `repr` ist kürzeste-Rundreise und damit von der
Formatierungsentscheidung des Interpreters abhängig. `.hex()` ist genau das
Bitmuster, und es ist über Interpreter-Versionen stabil.
"""

from __future__ import annotations

import dataclasses
import hashlib

#: Länge der Schlüssel. Sechzehn Hex-Zeichen sind 64 Bit; bei einigen
#: hunderttausend Entscheidungen über die Lebensdauer des Projekts liegt die
#: Kollisionswahrscheinlichkeit weit unter jeder anderen Fehlerquelle hier.
#: Länger als der Entscheidungsstempel (12), weil es viel mehr Entscheidungen
#: als Codeversionen gibt.
_ID = 16

_SEP = "\x00"


class OrphanFillError(RuntimeError):
    """Ein Fill verweist auf eine Entscheidung, die es nicht gibt."""


class ContradictoryDecisionError(RuntimeError):
    """Zweimal derselbe Schlüssel mit verschiedenem Inhalt.

    Kann durch die Konstruktion nicht passieren, solange die ID abgeleitet
    wird -- und steht hier genau darum: wenn sie doch passiert, ist entweder
    der Hash kollidiert oder jemand hat eine ID übergeben.
    """


class ContradictorySignatureError(RuntimeError):
    """Fill und Entscheidung behaupten verschiedene Läufe.

    Der Fall, den die 78 widersprüchlichen Signaturen vom 11.10.2026 gezeigt
    haben. Er ist still: beide Zeilen sind einzeln plausibel.
    """


def _teil(wert: object) -> str:
    """Ein Feld in kanonischer Form. Floats exakt, alles andere als Text."""
    if isinstance(wert, float):
        return wert.hex()
    if isinstance(wert, bool):
        # Vor `int`, weil bool eine Unterklasse davon ist.
        return "true" if wert else "false"
    return str(wert)


@dataclasses.dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Was entschieden wurde, mit einem Schlüssel aus seinem eigenen Inhalt.

    Die Feldreihenfolge ist Teil der Definition: sie zu ändern ändert jeden
    Schlüssel, und das ist richtig, weil der kanonische Text die Definition
    *ist*.
    """

    identity_stamp: str
    """Der Stempel des Laufs (`ExperimentIdentity.stamp()`).

    Er gehört in den Schlüssel, damit dieselbe Marktsituation unter zwei
    verschiedenen Gebührenplänen zwei verschiedene Entscheidungen ist. Ohne ihn
    würden die Fills zweier Läufe auf eine Entscheidung zeigen, und genau das
    ist die Verunreinigung, um die es hier geht.
    """

    symbol: str
    decided_ts: int
    side: str
    entry: float
    stop: float
    target: float
    setup_key: str
    setup_source: str
    signal_timeframe: str

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            wert = getattr(self, field.name)
            if isinstance(wert, str) and not wert.strip():
                raise ValueError(
                    f"{field.name} ist leer -- eine Entscheidung ohne "
                    f"{field.name} laesst sich spaeter keiner zuordnen"
                )
            if isinstance(wert, str) and _SEP in wert:
                raise ValueError(f"{field.name} enthaelt das Trennzeichen")

    def canonical(self) -> str:
        return _SEP.join(
            f"{field.name}={_teil(getattr(self, field.name))}"
            for field in dataclasses.fields(self)
        )

    @property
    def decision_id(self) -> str:
        """Abgeleitet, niemals übergeben. Siehe den Modultext."""
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()[:_ID]


@dataclasses.dataclass(frozen=True, slots=True)
class FillProvenance:
    """Woher ein Fill kam -- die dreizehn Angaben, die ihn erklärbar machen.

    Jede modellierte Grösse steht neben ihrer tatsächlichen, und die
    tatsächliche darf fehlen. Das ist der Punkt: in der Simulation gibt es
    keine, live gibt es beide, und **der Unterschied zwischen ihnen ist die
    Messung**, auf die der ganze Ausführungsteil dieses Projekts wartet. Ein
    einziges Feld „Fillpreis" hätte diese Messung unmöglich gemacht.
    """

    decision_id: str
    identity_stamp: str

    venue: str
    policy: str

    liquidity_role_modelled: str
    """`maker` oder `taker`, wie das Modell es angenommen hat."""

    liquidity_role_actual: str | None
    """Was die Börse berichtet hat. `None` in jeder Simulation.

    Solange dieses Feld leer ist, ist `maker_role_proven` zu Recht `False`. Es
    zu füllen ist die einzige Art, diese Annahme zu beweisen.
    """

    fee_rate: float
    """Der Satz, den das Modell angewendet hat."""

    fee_rate_actual: float | None
    fee_paid: float
    """Der Betrag, modelliert oder tatsächlich -- je nachdem, was vorlag."""

    reference_price: float
    """Der Preis, gegen den entschieden wurde.

    Getrennt vom Fillpreis, weil die Differenz der Schlupf ist. Ohne das Feld
    ist Schlupf eine Annahme und keine Messung.
    """

    fill_price_modelled: float
    fill_price_actual: float | None

    execution_id: str | None
    order_id: str | None

    def __post_init__(self) -> None:
        if not self.decision_id.strip():
            raise OrphanFillError(
                "ein Fill ohne decision_id ist eine Waise -- sie laeuft in "
                "jeder Auswertung mit und ist in keiner erklaerbar"
            )
        for name in ("identity_stamp", "venue", "policy", "liquidity_role_modelled"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} ist leer")
        for name in ("liquidity_role_modelled", "liquidity_role_actual"):
            rolle = getattr(self, name)
            if rolle is not None and rolle not in ("maker", "taker"):
                raise ValueError(
                    f"{name}={rolle!r} ist keine Liquidity Role; erlaubt sind "
                    f"'maker' und 'taker'"
                )

    @property
    def slippage(self) -> float | None:
        """Gemessener Schlupf, oder `None`, wenn kein echter Fillpreis vorliegt.

        `None` und nicht `0.0`: eine Null würde behaupten, es sei gemessen
        worden und habe nichts ergeben.
        """
        if self.fill_price_actual is None:
            return None
        return self.fill_price_actual - self.fill_price_modelled

    @property
    def role_was_as_modelled(self) -> bool | None:
        if self.liquidity_role_actual is None:
            return None
        return self.liquidity_role_actual == self.liquidity_role_modelled


class ProvenanceLedger:
    """Entscheidungen und Fills, mit referentieller Integrität beim Schreiben.

    Die Prüfung sitzt beim Schreiben und nicht in einem nachträglichen Bericht.
    Der Grund ist Erfahrung: ein nachträglicher Bericht findet die Waise, wenn
    sie schon in drei Auswertungen steht.
    """

    def __init__(self) -> None:
        self._decisions: dict[str, DecisionRecord] = {}
        self._fills: list[FillProvenance] = []

    # -- Schreiben ---------------------------------------------------------- #

    def register(self, decision: DecisionRecord) -> str:
        """Eine Entscheidung aufnehmen und ihren Schlüssel zurückgeben.

        Zweimal dieselbe Entscheidung ist erlaubt und idempotent -- ein Replay
        trifft dieselbe Entscheidung wieder, und das ist kein Fehler, sondern
        die Eigenschaft, die einen Inhaltshash wertvoll macht.
        """
        key = decision.decision_id
        vorhanden = self._decisions.get(key)
        if vorhanden is not None and vorhanden != decision:
            raise ContradictoryDecisionError(
                f"decision_id {key} traegt zwei verschiedene Inhalte:\n"
                f"  vorhanden: {vorhanden.canonical()!r}\n"
                f"  neu:       {decision.canonical()!r}\n"
                f"Entweder ist der Hash kollidiert oder eine ID wurde "
                f"uebergeben statt abgeleitet."
            )
        self._decisions[key] = decision
        return key

    def record(self, fill: FillProvenance) -> None:
        """Einen Fill aufnehmen -- oder abbrechen.

        Zwei Gründe für einen Abbruch, und beide sind in diesem Projekt
        gemessen worden: eine Waise (17.10.2026, ein Trade ohne Konto) und
        zwei widersprüchliche Signaturen (11.10.2026, 78 Fälle).
        """
        decision = self._decisions.get(fill.decision_id)
        if decision is None:
            raise OrphanFillError(
                f"Fill verweist auf decision_id {fill.decision_id}, die hier "
                f"nicht registriert ist. {len(self._decisions)} Entscheidungen "
                f"bekannt. Ein Fill ohne Entscheidung ist verboten."
            )
        if decision.identity_stamp != fill.identity_stamp:
            raise ContradictorySignatureError(
                f"Fill sagt Lauf {fill.identity_stamp}, seine Entscheidung "
                f"sagt {decision.identity_stamp}. Beide Zeilen sind einzeln "
                f"plausibel -- zusammen sind sie zwei Laeufe."
            )
        self._fills.append(fill)

    # -- Lesen -------------------------------------------------------------- #

    @property
    def decisions(self) -> tuple[DecisionRecord, ...]:
        return tuple(self._decisions.values())

    @property
    def fills(self) -> tuple[FillProvenance, ...]:
        return tuple(self._fills)

    def decision_of(self, fill: FillProvenance) -> DecisionRecord:
        return self._decisions[fill.decision_id]

    def orphans(self) -> tuple[FillProvenance, ...]:
        """Immer leer, solange nur über `record` geschrieben wurde.

        Steht trotzdem hier, weil ein Speicher auch aus einer Datei gefüllt
        werden kann, die vor dieser Prüfung entstanden ist -- und dann ist die
        Frage echt.
        """
        return tuple(f for f in self._fills if f.decision_id not in self._decisions)

    def unfilled(self) -> tuple[DecisionRecord, ...]:
        """Entscheidungen ohne Fill. Kein Fehler -- die meisten werden abgelehnt.

        Die Gegenrichtung zur Waise, und ausdrücklich erlaubt: von 4.446
        Absichten in ADAUSDT wurden 3.703 von Risikoregeln abgelehnt. Eine
        Entscheidung ohne Fill ist der NORMALFALL, ein Fill ohne Entscheidung
        ist der Defekt. Die beiden zu verwechseln hiesse, die Ablehnungen zu
        verlieren -- und die sind selbst eine Messung.
        """
        gefuellt = {f.decision_id for f in self._fills}
        return tuple(d for d in self._decisions.values() if d.decision_id not in gefuellt)
