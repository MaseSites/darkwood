"""Welche Ablehnung eine Auswahlregel überstimmen darf — an EINER Stelle.

**Der Anlass ist ein Defekt, nicht ein Bedürfnis nach Ordnung.** Es gab
`SAFETY_RULES` zweimal, mit demselben Namen, demselben erklärten Zweck
(„Ablehnungsgründe, die eine Auswahlregel NICHT überstimmen darf") und
verschiedenen Mengen:

    scripts/study_exits.py       {liquidation, chance_risiko, kosten, grenzen}
    scripts/study_meta_label.py  {liquidation, grenzen}

Die beiden Studien beantworteten damit dieselbe Frage verschieden, und nichts
glich sie ab. Gefunden hat es das Audit vom 13.10.2026, als vor dem Hinzufügen
eines Enum-Werts die Leser aufgezählt wurden — ohne diese Aufzählung wäre ein
sechster Wert in genau eine der beiden Mengen gewandert, und welche, hätte vom
Zufall abgehangen. Das Audit hat die Zusammenlegung vertagt, weil sie bedeutet,
sich für eine Menge zu entscheiden.

**Was hier entschieden wird, und was nicht.** Welche Menge „richtig" ist, lässt
sich nicht messen, denn die Frage ist nicht, wie der Markt sich verhält, sondern
was ein Ergebnis **lizenziert**. Entschieden ist deshalb nur das:

* Die Menge steht an einer Stelle und hat zwei benannte Lesarten.
* Die strenge ist die Vorgabe, weil nur ihr Ergebnis ohne Regeländerung
  umsetzbar ist.
* Die weite bleibt erlaubt, muss aber **ausdrücklich gewählt** werden, und eine
  Studie, die sie wählt, sagt es in ihrer Ausgabe. Genau das fehlte: zwei
  Populationen, die sich still unterschieden.

**Die Struktur dahinter, und sie ist nicht beliebig.** Die sechs Gründe teilen
sich in drei Arten:

`liquidation` und `grenzen` sind **gar nicht verhandelbar**. Das erste ist
Physik — eine Position, deren Liquidation vor dem Stop liegt, verliert mehr als
geplant, und kein Modell ändert das. Das zweite ist ein Urteil über das KONTO
und nicht über das Signal: Tagesverlust, Wochenverlust, Abkühlung, Zahl offener
Positionen. Dasselbe Signal wäre an einem anderen Tag durchgegangen, also sagt
seine Ablehnung nichts über es aus, was eine Auswahlregel verbessern könnte.

`chance_risiko` und `kosten` sind **Urteile über die Wirtschaftlichkeit des
Signals**, und ein Modell könnte sie im Prinzip in Frage stellen. Nur sind es
Produktionsregeln in `sim/plan.py`: ein positives Ergebnis, das sie überstimmt,
ist ohne Änderung einer Schutzregel nicht umsetzbar. Es ist dann kein Befund,
sondern ein Änderungswunsch ohne Nachweis. Dazu kommt, dass beide Regeln
gemessen bestätigt sind — die Population, die sie ablehnen, ist brutto negativ
mit einem Intervall ohne Null, über zwölf Märkte.

`zuversicht` und `groesse` stehen in KEINER der beiden Mengen, und das war in
beiden Dateien schon so. `groesse` ist eine Venue-Grenze (die Börse nimmt die
Position nicht an), `zuversicht` ist die Schwelle des Modells selbst — eine
Auswahlregel, die sie nicht überstimmen dürfte, wäre keine Auswahlregel.

Hier und nicht in `domain/enums.py`: diese Mengen beschreiben, was eine STUDIE
darf, nicht wie der Händler entscheidet. `learn/` liegt ausserhalb des
Entscheidungs-Abschlusses, also bewegt eine Änderung hier den
Entscheidungsstempel nicht — und ein überflüssiger Schnitt der
Vorwärtsstichprobe kostet Stichprobe.
"""

from __future__ import annotations

from traidingbrain.domain.enums import Rule

#: Nicht verhandelbar, auch nicht im Prinzip. Physik und Kontostand.
NEVER_OVERRIDABLE: frozenset[str] = frozenset({Rule.LIQUIDATION, Rule.LIMITS})

#: Verhandelbar, aber nur gegen eine Regeländerung. Beides sind
#: Produktionsregeln in `sim/plan.py`, und beide sind gemessen bestätigt.
NEEDS_A_RULE_CHANGE: frozenset[str] = frozenset({Rule.REWARD_RISK, Rule.COSTS})

#: Die Vorgabe. Eine Studie, die hierauf filtert, liefert ein Ergebnis, das
#: ohne Änderung einer Schutzregel umsetzbar ist.
INVIOLABLE: frozenset[str] = NEVER_OVERRIDABLE | NEEDS_A_RULE_CHANGE


def safety_rules(*, allow_rule_change: bool = False) -> frozenset[str]:
    """Die Ablehnungsgründe, die diese Studie nicht überstimmen darf.

    `allow_rule_change=True` ist die weite Lesart: die Studie darf Signale
    betrachten, die der Kostendeckel oder das Mindest-Chance-Risiko abgelehnt
    hat. Ihr Ergebnis ist dann **nicht umsetzbar, ohne eine Schutzregel zu
    ändern**, und das gehört in ihre Ausgabe — `describe()` liefert den Satz
    dafür.

    Das Schlüsselwort ist Absicht. `safety_rules(False)` an einer Aufrufstelle
    wäre wieder eine stille Entscheidung, und die stille Entscheidung war der
    ganze Defekt.
    """
    return NEVER_OVERRIDABLE if allow_rule_change else INVIOLABLE


def describe(*, allow_rule_change: bool = False) -> str:
    """Eine Zeile für den Kopf eines Studienberichts.

    Sie existiert, damit zwei Studien mit verschiedenen Populationen nicht
    mehr gleich aussehen. Wer die Berichte nebeneinanderlegt, sieht den
    Unterschied, statt ihn aus zwei Quelldateien erschliessen zu müssen.
    """
    rules = sorted(safety_rules(allow_rule_change=allow_rule_change))
    if not allow_rule_change:
        return (
            f"Unantastbare Ablehnungen: {', '.join(rules)} (Vorgabe). "
            "Ein Ergebnis hier ist ohne Regeländerung umsetzbar."
        )
    return (
        f"Unantastbare Ablehnungen: {', '.join(rules)} (WEITE Lesart). "
        "Die Studie betrachtet Signale, die "
        f"{', '.join(sorted(NEEDS_A_RULE_CHANGE))} abgelehnt hat -- ein "
        "positives Ergebnis ist damit NICHT umsetzbar, ohne eine Schutzregel "
        "zu aendern, und braucht dafuer einen eigenen Nachweis."
    )
