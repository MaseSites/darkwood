"""Welche Ablehnung eine Auswahlregel überstimmen darf — einmal, nicht zweimal.

**Der Defekt, den diese Datei festnagelt.** `SAFETY_RULES` gab es zweimal, mit
demselben Namen, demselben erklärten Zweck und verschiedenen Mengen:

    scripts/study_exits.py       {liquidation, chance_risiko, kosten, grenzen}
    scripts/study_meta_label.py  {liquidation, grenzen}

Zwei Studien beantworteten dieselbe Frage verschieden, und nichts glich sie ab.
Das Audit vom 13.10.2026 hat es gefunden, weil vor dem Hinzufügen eines
Enum-Werts die Leser aufgezählt wurden — ohne diese Aufzählung wäre ein sechster
Wert in genau eine der beiden Mengen gewandert, und welche, hätte vom Zufall
abgehangen.

Die Tests hier prüfen drei Dinge, und das dritte ist das wichtigste:

1. Die beiden Lesarten enthalten das, was sie behaupten.
2. Die Zusammenlegung hat **keine Population verändert** — jede Studie liest
   genau die Menge, die sie vorher hart stehen hatte.
3. Die weite Lesart muss AUSDRÜCKLICH gewählt werden und sagt es in der
   Ausgabe. Eine stille Entscheidung war der ganze Defekt.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import study_exits  # noqa: E402
import study_meta_label  # noqa: E402

from traidingbrain.domain.enums import Rule  # noqa: E402
from traidingbrain.learn.overrides import (  # noqa: E402
    INVIOLABLE,
    NEEDS_A_RULE_CHANGE,
    NEVER_OVERRIDABLE,
    OVERRIDABLE_BY_SELECTION,
    describe,
    safety_rules,
)

#: Die Mengen, wie sie bis zum 14.10.2026 in den beiden Skripten standen.
#: Literal, nicht abgeleitet: eine Menge, die genauso gebaut wird wie die
#: geprüfte, stimmt mit jedem Fehler überein.
AS_SHIPPED_IN_EXITS = {"liquidation", "chance_risiko", "kosten", "grenzen"}
AS_SHIPPED_IN_META = {"liquidation", "grenzen"}


def test_the_strict_reading_is_what_study_exits_had() -> None:
    """Die Zusammenlegung darf keine Population verschieben.

    Täte sie es, wäre jedes schon berichtete Ergebnis von E3 über eine andere
    Menge Trades gerechnet als sein Bericht sagt -- eine Aufräumarbeit, die
    still ein Ergebnis ändert.
    """
    assert set(safety_rules()) == AS_SHIPPED_IN_EXITS


def test_the_wide_reading_is_what_study_meta_label_had() -> None:
    assert set(safety_rules(allow_rule_change=True)) == AS_SHIPPED_IN_META


def test_the_strict_reading_is_the_default() -> None:
    """Ohne Schlüsselwort die Menge, deren Ergebnis umsetzbar ist."""
    assert safety_rules() == INVIOLABLE
    assert INVIOLABLE == NEVER_OVERRIDABLE | NEEDS_A_RULE_CHANGE


def test_a_plain_string_matches_the_set() -> None:
    """`refused_by` ist in der Datenbank eine Zeichenkette, keine `Rule`.

    `StrEnum`-Mitglieder hashen wie ihr Wert, also funktioniert das -- aber
    "funktioniert vermutlich" ist bei einer Mengenzugehörigkeit die
    gefährlichste Vermutung, die es gibt: sie gibt still `False` zurück und
    jede Studie filtert dann nichts weg.
    """
    assert "kosten" in INVIOLABLE
    assert Rule.COSTS in INVIOLABLE
    assert "liquidation" in NEVER_OVERRIDABLE
    assert None not in INVIOLABLE


def test_confidence_and_size_are_in_neither_reading() -> None:
    """Und das war in beiden Dateien schon so.

    `groesse` ist eine Venue-Grenze, `zuversicht` die Schwelle des Modells
    selbst -- eine Auswahlregel, die ihre eigene Schwelle nicht überstimmen
    dürfte, wäre keine Auswahlregel.
    """
    for rule in (Rule.CONFIDENCE, Rule.SIZE):
        assert rule not in INVIOLABLE
        assert rule not in NEVER_OVERRIDABLE


def test_every_rule_is_accounted_for() -> None:
    """Ein siebter Enum-Wert muss hier auffallen, nicht stillschweigend fehlen.

    Genau das war der Fehler, der zum Doppel führte: ein sechster Wert
    (`grenzen`) kam dazu, und welche der beiden Mengen ihn bekam, hätte vom
    Zufall abgehangen. Jetzt gibt es eine Stelle -- und dieser Test besteht
    darauf, dass jeder Grund dort eingeordnet ist.
    """
    sorted_out = INVIOLABLE | OVERRIDABLE_BY_SELECTION
    missing = [rule.value for rule in Rule if rule not in sorted_out]
    assert not missing, (
        f"diese Ablehnungsgruende sind nirgends eingeordnet: {missing}. "
        "Entscheide, ob eine Auswahlregel sie ueberstimmen darf, und schreibe "
        "es in learn/overrides.py -- nicht in die aufrufende Studie."
    )


def test_the_wide_reading_announces_itself() -> None:
    """Der Satz, der vorher fehlte.

    Zwei Studien mit verschiedenen Populationen sahen gleich aus. Wer die
    Berichte nebeneinanderlegte, konnte den Unterschied nur aus zwei
    Quelldateien erschliessen.
    """
    strict = describe()
    wide = describe(allow_rule_change=True)

    assert strict != wide
    assert "ohne Regeländerung umsetzbar" in strict
    assert "NICHT umsetzbar" in wide
    for rule in NEEDS_A_RULE_CHANGE:
        assert rule.value in wide, (
            "die weite Lesart muss benennen, WELCHE Regel sie uebergeht"
        )


def test_both_studies_read_from_the_one_place() -> None:
    """Sonst kommt das Doppel zurück, und zwar unbemerkt.

    Der Test importiert die echten Skripte. Eine Studie, die ihre Menge
    wieder selbst hinschreibt, fällt hier -- und das ist der einzige Schutz
    davor, denn ein zweites Literal sieht im Diff harmlos aus.
    """
    assert set(study_exits.SAFETY_RULES) == set(safety_rules())
    assert set(study_meta_label.SAFETY_RULES) == set(
        safety_rules(allow_rule_change=True)
    )
    assert "NICHT umsetzbar" in study_meta_label.SAFETY_NOTE
