"""Welcher Lauf eine Zeile geschrieben hat -- vollständig, nicht ungefähr.

**Warum `run_signature` dafür nicht erweitert wird.** Die vorhandene Signatur
ist ein *Schlüssel*: 12.843 Zeilen im Signalspeicher sind unter ihren exakten
Zeichenketten abgelegt, und `version.py` hängt jeden Zusatz nur dann an, wenn er
vom historischen Anker abweicht, damit keine Zeile verwaist. Zwölf weitere
bedingte Zusätze wären nicht lesbar, und schlimmer: der historische Anker für
die *Venue* ist selbst ein Widerspruch -- Bybit-Etikett auf Binance-Kerzen. Ein
Feld, das „nichts anhängen, wenn es dem Anker entspricht" bedeutet, hätte genau
diesen Fehler zum Vorgabewert gemacht.

Darum eine zweite, vollständige Identität daneben. Sie trägt `run_signature`
*mit*, statt sie zu ersetzen -- der alte Schlüssel bleibt gültig, und die neue
Identität sagt zusätzlich, unter welcher Börse, welchem Gebührenplan und welchem
Füllmodell die Zeile entstand. Die Direktive erlaubt beides ausdrücklich
(„`run_signature` **beziehungsweise** die neue Experimentidentität").

**Warum der Gebührenplan ein Identitätsfeld ist und keine Fussnote.** Am
18.10.2026 gemessen: dieselben 7.335 Fills unter Bybits Takersatz und unter
Binances Takersatz unterscheiden sich um +0.0014 R je Trade, mit einem Intervall
von [+0.001, +0.002] -- also reliabel, und in allen zwölf Märkten
gleichgerichtet. Zwei Läufe, die sich nur in dieser Tabelle unterscheiden, sind
verschiedene Läufe. Ohne das Feld hätten sie sich glatt mitteln lassen.

**Die eine Eigenschaft, die dieses Modul trägt.** Jedes Feld muss den Stempel
bewegen. Ein Feld, das in der Aufzeichnung steht und nicht im Hash, ist ein Loch
-- und ein Loch meldet sich nie. `tests/test_experiment_identity.py` prüft das
nicht als Behauptung, sondern feldweise: es verändert jedes Feld einzeln und
verlangt einen anderen Stempel. Genau dieser Test hätte den Befund „in der
Legacy-Signatur stand die Venue NICHT" vor einem Jahr gefunden.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping
from typing import Any

from traidingbrain.journal.version import decision_version, run_signature

#: Länge des Identitätsstempels, dieselbe Begründung wie bei
#: `decision_version`: zwölf Hex-Zeichen sind 48 Bit.
_STAMP = 12

#: Trennzeichen im kanonischen Text. Ein Nullbyte, weil es in keinem der Werte
#: vorkommen kann -- mit einem Doppelpunkt wären `a:b|c` und `a|b:c` dieselbe
#: Zeichenkette, und zwei verschiedene Läufe hätten denselben Stempel.
_SEP = "\x00"

#: Die Felder, bei denen „leer" eine Aussage ist und keine Lücke.
#:
#: Jedes andere leere Feld bricht ab. Diese drei nicht, und zwar weil ihre
#: Leere etwas bedeutet: kein Ausführungspfad (der heutige Zustand -- alle
#: Kerzen sind Binance, ausführbar ist nur Bybit), und kein Venue-Widerspruch.
#:
#: Die Liste ist bewusst kurz und bewusst eine Konstante. Als Prüfung an drei
#: Stellen im Rumpf wäre sie beim vierten Feld auseinandergelaufen.
_LEER_ERLAUBT = frozenset(
    {"execution_venue", "execution_environment", "incoherence_reason"}
)


class IncompleteIdentityError(ValueError):
    """Ein Identitätsfeld ist leer.

    Fail-closed, und zwar aus Erfahrung: ein leeres Feld ist nicht „unbekannt",
    es ist eine Zeile, die sich später mit jeder anderen leeren Zeile mitteln
    lässt. Wer eine Komponente nicht kennt, schreibt hin, dass er sie nicht
    kennt (`"unbekannt"`), und dann ist das ein eigener Lauf.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class ExperimentIdentity:
    """Die vollständige Herkunft eines Laufs, in einer hashbaren Aufzeichnung.

    Die Feldreihenfolge ist die kanonische Reihenfolge. Sie zu ändern bewegt
    jeden Stempel -- was richtig ist, denn die Reihenfolge ist Teil der
    Definition und keine Darstellungsfrage.
    """

    # -- Woher die Zahlen kommen ------------------------------------------- #

    analysis_venue: str
    """Die Börse, deren Kerzen die Analyse gelesen hat.

    Getrennt von `data_venue`, weil die beiden auseinanderfallen können und am
    18.10.2026 auseinanderfielen: `analysis/context.py` trägt `venue="bybit"`
    hartkodiert, während `config/settings.yaml` auf `binance` steht. Ein
    einziges Feld hätte den Widerspruch unsichtbar gemacht; zwei Felder
    schreiben ihn auf.
    """

    data_venue: str
    price_venue: str
    price_environment: str
    instrument_spec_venue: str
    """Von welcher Börse Tick, Schrittweite, Mindestnominal und Gebühren kamen.

    Das war der Befund vom 18.10.2026: `DEFAULT_SPEC` trug Bybits Takersatz,
    während alle Kerzen von Binance kamen.
    """

    execution_venue: str | None
    execution_environment: str | None

    # -- Was gekostet und wie gefüllt wurde -------------------------------- #

    policy: str
    """`ExecutionPolicy.fingerprint()` -- Orderarten, Sätze, Makerbeweis."""

    fee_schedule: str
    """WELCHE Gebührentabelle, nicht welche Zahlen.

    Beides, weil nur beides zusammen den Befund fängt. `policy` trägt die
    Sätze; wären nur sie aufgezeichnet, hätte „0.00055" nicht verraten, dass es
    Bybits 0.00055 auf Binance-Daten war. Der Name der Tabelle verrät es.
    """

    fill_model: str
    slippage_model: str
    funding_source: str

    # -- Welche Daten, welcher Code ---------------------------------------- #

    data_version: str
    """Die Datenlage, MIT ihrer Methode davor (`coverage:` oder `content:`).

    Die Methode steht im Wert, damit ein billiger und ein teurer Datenstempel
    nicht verwechselbar sind. Das ist nicht Pedanterie: ein Abdeckungsstempel
    bewegt sich **nicht**, wenn eine Quelle ihre eigene Vergangenheit
    umschreibt, ohne das Fenster zu ändern. Genau diese Blindheit ist am
    15.10.2026 beim Mutationstest schon einmal aufgefallen und steht darum hier
    im Wert und nicht nur in einem Kommentar.
    """

    strategy_version: str
    decision_version: str

    # -- Portfolio und der alte Schlüssel ---------------------------------- #

    portfolio: str

    incoherence_reason: str
    """Warum dieser Lauf zwei Börsen mischt -- oder leer, wenn er es nicht tut.

    **Leer ist hier ein echter Wert und keine Lücke**, dieselbe Begründung wie
    bei den beiden Ausführungsfeldern: „dieser Lauf ist kohärent" ist eine
    Aussage.

    Das Feld steht hier, weil es ohne es nicht in der Ergebnisdatei stünde. Die
    Identität trägt `policy.fingerprint()`, nicht `binding.fingerprint()` --
    der Grund, den `VenueBinding.legacy_incoherent` verlangt, wäre also in der
    Bindung verblieben und beim Serialisieren verschwunden. Genau das ist der
    Fehler, den diese ganze Phase behandelt: eine Angabe, die es gibt und die
    nicht in den Daten landet.
    """

    run_signature: str
    """Die Legacy-Signatur, unverändert mitgetragen.

    Mitgetragen und nicht ersetzt: die vorhandenen Zeilen sind darunter
    abgelegt, und eine Identität, die den alten Schlüssel wegwirft, trennt die
    neue Messung von jeder alten.
    """

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if value is None:
                # Nur die beiden Ausführungsfelder dürfen fehlen, und zwar
                # weil „kein Ausführungspfad" ein echter Zustand ist und keine
                # Lücke. Jedes andere None wäre eine nicht gestellte Frage.
                if field.name in _LEER_ERLAUBT:
                    continue
                raise IncompleteIdentityError(
                    f"{field.name} ist None. Leer sein duerfen nur: "
                    f"{', '.join(sorted(_LEER_ERLAUBT))}."
                )
            if field.name in _LEER_ERLAUBT:
                continue
            if isinstance(value, str) and not value.strip():
                raise IncompleteIdentityError(
                    f"{field.name} ist leer. Eine leere Komponente mittelt sich "
                    f"spaeter mit jeder anderen leeren zusammen -- wer sie nicht "
                    f"kennt, schreibt 'unbekannt' hin, und dann ist es ein "
                    f"eigener Lauf."
                )
            if isinstance(value, str) and _SEP in value:
                # Sonst waere "das Trennzeichen kommt in keinem Wert vor" eine
                # Hoffnung. Ein Wert, der es enthaelt, kann eine Feldgrenze
                # vortaeuschen, und dann stempeln zwei verschiedene
                # Identitaeten gleich.
                raise IncompleteIdentityError(
                    f"{field.name} enthaelt das Trennzeichen (Nullbyte). Damit "
                    f"liesse sich eine Feldgrenze vortaeuschen."
                )

    # -- Identität ---------------------------------------------------------- #

    def canonical(self) -> str:
        """Der Text, über den gehasht wird. Lesbar, damit ein Stempel erklärbar ist.

        Mit Feldnamen, nicht nur Werten: zwei Läufe, bei denen zwei Felder ihre
        Werte tauschen, hätten sonst denselben Stempel.
        """
        return _SEP.join(
            f"{field.name}={getattr(self, field.name)}"
            for field in dataclasses.fields(self)
        )

    def stamp(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()[:_STAMP]

    @property
    def executes(self) -> bool:
        return self.execution_venue is not None

    def venues_agree(self) -> bool:
        """Lesen Analyse, Daten, Preise und Instrumentregeln dieselbe Börse?

        Keine Prüfung, die etwas verbietet, sondern eine Frage, die ein Bericht
        stellen kann. Am 18.10.2026 lautet die Antwort **nein**, und das ist der
        Grund, warum es diese Methode gibt: der Widerspruch soll abfragbar sein,
        nicht nur in einem Audit stehen.
        """
        return (
            self.analysis_venue
            == self.data_venue
            == self.price_venue
            == self.instrument_spec_venue
        )

    # -- Serialisierung ----------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        return {
            field.name: getattr(self, field.name)
            for field in dataclasses.fields(self)
        }

    @classmethod
    def from_dict(cls, blob: Mapping[str, Any]) -> ExperimentIdentity:
        """Streng in beide Richtungen.

        Ein unbekannter Schlüssel ist ein Feld, das jemand hinzugefügt und hier
        nicht eingetragen hat -- stillschweigend verwerfen hiesse, es aus dem
        Stempel zu entfernen und damit zwei verschiedene Läufe gleich zu
        stempeln. Ein fehlender Schlüssel ist dasselbe in der Gegenrichtung.
        """
        erwartet = {field.name for field in dataclasses.fields(cls)}
        gegeben = set(blob)
        if fehlend := erwartet - gegeben:
            raise IncompleteIdentityError(
                f"Felder fehlen: {', '.join(sorted(fehlend))}"
            )
        if ueberzaehlig := gegeben - erwartet:
            raise IncompleteIdentityError(
                f"unbekannte Felder: {', '.join(sorted(ueberzaehlig))}. Ein "
                f"stillschweigend verworfenes Feld faellt aus dem Stempel."
            )
        return cls(**{name: blob[name] for name in erwartet})


# --------------------------------------------------------------------------- #
# Aus dem laufenden System heraus bauen
# --------------------------------------------------------------------------- #


def fill_model_of(config: object) -> str:
    """Welches Füllmodell gilt -- die Schalter, die entscheiden, OB gefüllt wird.

    Nicht „pessimistisch" als Etikett, sondern die vier Werte, aus denen das
    Verhalten folgt. Ein Etikett bleibt gleich, wenn ein Schalter umgelegt wird.
    """
    sim = config.engine.simulation  # type: ignore[attr-defined]
    frames = config.engine.timeframes  # type: ignore[attr-defined]
    return (
        f"intrabar={frames.execution.value}"
        f"|pessimistic={sim.pessimistic_intrabar}"
        f"|touch={sim.fill_on_touch}"
        f"|expiry={sim.entry_expiry_bars}bars"
    )


def slippage_model_of(config: object) -> str:
    """Wie viel Schlupf angenommen wird -- und worauf er angewendet wird.

    Die zweite Hälfte ist der Teil, der am 16.10.2026 einen doppelt gezählten
    Schlupf verursacht hat: `sim/broker.py:713` sagt, dass Limit-Einstiege
    **nicht** rutschen. Die Zahl allein hätte das nicht verraten.
    """
    sim = config.engine.simulation  # type: ignore[attr-defined]
    return f"{sim.slippage_bps:g}bps|limit-entries-do-not-slip"


def strategy_version_of(pool: object) -> str:
    """Pool-Name plus jede Setup-Fassung, sortiert.

    Die Fassungen stehen in den Setups selbst (`V08`, `V06`, ...). Sie gehören
    hierher, weil eine geänderte Setup-Regel eine andere Strategie ist, und
    `run_signature` nur die Liste der *aktiven Schlüssel* trägt -- nicht ihre
    Fassung. Zwei Läufe mit derselben Setup-Liste und einer neu geschriebenen
    Regel hatten bisher dieselbe Signatur.
    """
    setups = sorted(
        f"{setup.key}:{setup.source}"
        for setup in pool.setups  # type: ignore[attr-defined]
    )
    return f"{pool.name}|{','.join(setups)}"  # type: ignore[attr-defined]


def portfolio_of(config: object) -> str:
    """Die Portfolioeinstellungen, die entscheiden, welche Trades entstehen."""
    risk = config.risk  # type: ignore[attr-defined]
    return (
        f"{risk.sizing.basis}"
        f"|equity={config.engine.simulation.initial_equity:g}"  # type: ignore[attr-defined]
        f"|slots={risk.limits.max_open_positions}"
        f"|costcap={risk.limits.max_cost_fraction_of_risk:g}"
        f"|lev<={risk.leverage.max:g}"
    )



def identity_for(
    config: object,
    binding: Any,
    pool: Any,
    *,
    data_version: str,
    funding_source: str,
    analysis_venue: str,
    max_bars: int | None = None,
    shadow: bool = False,
) -> ExperimentIdentity:
    """Die Identität des Laufs, aus Konfiguration und Bindung abgeleitet.

    Drei Dinge sind hier ausdrücklich **Argumente** und nicht abgeleitet, weil
    sie der Aufrufer wissen muss und dieses Modul nicht:

    * `data_version` -- siehe das Feld. Welche Methode, entscheidet der
      Aufrufer, und der Wert trägt sie vorne.
    * `funding_source` -- welcher Speicher die Fundingreihe lieferte.
    * `analysis_venue` -- und das ist der unangenehmste. `analysis/context.py`
      trägt die Venue hartkodiert, im Widerspruch zur Konfiguration. Hier
      `config.engine.exchange.name` einzusetzen hiesse, den Widerspruch
      zuzudecken; ihn als Argument zu verlangen heisst, dass der Aufrufer
      hinschreiben muss, was wirklich gelesen wurde.

    `run_signature` wird mit denselben Argumenten gebildet wie überall sonst,
    damit die neue Identität und der alte Schlüssel auf dieselbe Zeile zeigen.
    """
    return ExperimentIdentity(
        analysis_venue=analysis_venue,
        data_venue=binding.data_venue,
        price_venue=binding.price_venue,
        price_environment=str(binding.price_environment),
        instrument_spec_venue=binding.instrument_spec_venue,
        execution_venue=binding.execution_venue,
        execution_environment=(
            str(binding.execution_environment)
            if binding.execution_environment is not None
            else None
        ),
        policy=binding.policy.fingerprint(),
        fee_schedule=binding.policy.fee_provenance,
        fill_model=fill_model_of(config),
        slippage_model=slippage_model_of(config),
        funding_source=funding_source,
        data_version=data_version,
        strategy_version=strategy_version_of(pool),
        decision_version=decision_version(),
        portfolio=portfolio_of(config),
        # Der Grund aus der Bindung, damit er in der Ergebnisdatei landet und
        # nicht in der Bindung verbleibt.
        incoherence_reason=getattr(binding, "incoherence_reason", ""),
        run_signature=run_signature(config, max_bars=max_bars, shadow=shadow),
    )
