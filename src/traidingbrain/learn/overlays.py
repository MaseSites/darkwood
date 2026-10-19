"""Regeln auf der Kapitalkurve — blind entworfen, hier nachgebaut.

**Herkunft.** Vier unabhängige Entwürfe, die die Verteilungskennzahlen der
7.335 Trades kannten, aber **nicht** den Kurvenverlauf und nicht den Zeitpunkt
des Höchststands. Das war Absicht: ich hatte die Kurve gesehen, und eine Regel,
die ich darauf zuschneide, beschreibt die Vergangenheit statt eine Politik.

**Die gemeinsame Arithmetik, die alle vier gefunden haben.** Der Logertrag je
Trade ist `m·f·EV - ½(m·f·SD)²`. Bei heutiger Grösse (f ≈ 4,39 % des Kontos je
R im Median, SD = 1,3552 R) ist die Drift -0,00057 und der Varianzabzug
-0,00177 — **der Abzug ist das 3,12-fache der Einstiegskante**. Weil die Drift
negativ ist, verbessert eine kleinere Exposition *beide* Terme zugleich: den
Abzug quadratisch, die Drift linear.

Daraus folgt die unbequeme Konsequenz: **die beste Regel dieser Familie ist
„kleiner", und ihr Grenzwert ist „gar nicht".** Jede Bremse kauft den linken
Rand mit dem rechten — der Anstieg auf 9.695 und sein Rückfall sind dasselbe
Objekt.

**Was trotzdem wirkt, und zwar ohne Vorhersage:** die Ratsche. Sie nimmt
Kapital endgültig aus dem Verzinsungsprozess, und als einziger Mechanismus kann
ein späterer Verlust das nicht rückgängig machen. Der Preis ist, dass das
geschützte Geld nicht mehr handelt.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

#: Die Grundeinstellung des Auftrags: 300 von 1.000 CHF, siebenfacher Hebel.
BASIS_ANTEIL, BASIS_HEBEL = 0.30, 7.0


class Zustand(Protocol):
    """Was eine Regel sehen darf. Der kuenftige Trade gehoert nicht dazu."""

    konto: float
    hoch: float
    start: float
    trade_nr: int
    letzte_r: tuple[float, ...]
    festgeschrieben: float

    @property
    def rueckgang(self) -> float: ...


#: Rueckgabe einer Regel: (Margin-Anteil, Hebel, geschuetzter Betrag) oder
#: None, wenn dieser Trade ausgelassen wird.
Wahl = tuple[float, float, float] | None

#: Eine Regel liest den Zustand und waehlt. Mehr darf sie nicht.
Regel = Callable[[Zustand], Wahl]


def kleiner(anteil: float, hebel: float) -> Regel:
    """Einfach kleiner handeln -- die Regel ohne jede Vorhersage.

    Sie ist der eigentliche Hauptkandidat dieser Datei, und das ist ein
    unbequemes Ergebnis: die wirksamste Massnahme auf einer Kurve mit negativer
    Drift ist, weniger Kapital daran zu haengen.
    """

    def regel(z: Zustand) -> Wahl:
        return (anteil, hebel, 0.0)

    return regel


def bremse(
    schwellen: tuple[float, ...],
    faktoren: tuple[float, ...],
    *,
    hysterese: float = 0.05,
) -> Regel:
    """Rueckgangsbremse: faellt das Konto vom Hoch, schrumpft die Groesse.

    Die Hysterese verhindert das Hin- und Herschalten an der Schwelle. Ohne sie
    produziert die Regel nur Gebuehren.

    **Die Asymmetrie, die sie strukturell hat und die nicht behebbar ist:** der
    Rueckgang wird bei voller Groesse bezahlt, die Erholung bei verkleinerter
    eingesammelt. Jedes V in der Kurve wird dadurch zu einem L.
    """

    def regel(z: Zustand) -> Wahl:
        d = z.rueckgang
        stufe = 0
        for i, s in enumerate(schwellen, start=1):
            if d >= s - (hysterese if stufe >= i else 0.0):
                stufe = i
        m = faktoren[min(stufe, len(faktoren) - 1)]
        if m <= 0:
            return None
        return (BASIS_ANTEIL * m, BASIS_HEBEL, 0.0)

    return regel


def ratsche(anteil_gesichert: float) -> Regel:
    """Bei jedem neuen Hoch wird ein Anteil des Kontos stillgelegt.

    **Die einzige Regel hier, die eine echte Zusage macht.** Der Sockel faellt
    nie, also kann ein spaeterer Verlust ihn nicht aufheben -- im Gegensatz zu
    jeder Bremse, deren Nutzen ein kuenftiger Gewinn wieder einkassiert.

    Und ihr Preis steht im selben Satz: das gesicherte Geld handelt nicht mehr.
    „Nach den knapp 10.000 nicht verlieren" heisst in dieser Regel woertlich:
    dann hoert man mit diesem Teil auf.
    """
    sockel = {"wert": 0.0, "hoch": 0.0}

    def regel(z: Zustand) -> Wahl:
        if z.konto > sockel["hoch"]:
            sockel["hoch"] = z.konto
            sockel["wert"] = max(sockel["wert"], anteil_gesichert * z.konto)
        handelbar = z.konto - sockel["wert"]
        if handelbar <= z.start * 0.01:
            return None
        return (BASIS_ANTEIL, BASIS_HEBEL, sockel["wert"])

    return regel


def progressiv(z: Zustand) -> Wahl:
    """Die GEGENPROBE: mehr Groesse nach Verlusten.

    Muss am schlechtesten enden. Steht hier, weil eine Familie ohne ihren
    Gegenpol nicht geprueft ist -- wenn dieser Arm NICHT der schlechteste ist,
    stimmt etwas am Pruefstand nicht.
    """
    verluste = sum(1 for r in z.letzte_r[-5:] if r < 0)
    return (BASIS_ANTEIL * (1.0 + 0.2 * verluste), BASIS_HEBEL, 0.0)


#: Die Regeln, die `scripts/study_equity_overlay.py` prueft -- als FABRIKEN.
#:
#: **Fabriken und nicht fertige Regeln, und das ist ein behobener Fehler.** Die
#: Ratsche haelt einen Sockel in einem Abschluss. Lag die Regel fertig in dieser
#: Liste, trug sie ihren Sockel aus dem vorigen Durchlauf in den naechsten --
#: und weil dort das Konto wieder bei 1.000 anfing, war `handelbar` negativ und
#: die Regel handelte NIE. Der Pruefstand meldete daraufhin fuer beide Ratschen
#: einen Median von exakt 1,0000x.
#:
#: Verraten hat es die Genauigkeit: 1,0000x auf vier Nachkommastellen, zweimal.
#: Eine Kennzahl, die auf jedem Lauf denselben Wert liest, ist eine Konstante
#: mit einem Etikett -- hier die Konstante "hat nicht gehandelt".
#:
#: Jede Fabrik liefert jetzt eine FRISCHE Regel je Durchlauf. Zustandslose
#: Regeln sind davon unberuehrt; die Fabrik kostet sie nichts.
#:
#: Bewusst wenige und mechanisch verschiedene statt aller zwanzig Einstellungen
#: der vier Entwuerfe: die Entwuerfe unterscheiden sich in Parametern, nicht in
#: Mechanismen, und ein Pruefstand, der zwanzig Varianten desselben Hebels
#: misst, misst zwanzigmal dasselbe.
REGELN: list[tuple[str, Callable[[], Regel]]] = [
    ("kleiner: 10 % / 2x", lambda: kleiner(0.10, 2.0)),
    ("kleiner: 5 % / 1x", lambda: kleiner(0.05, 1.0)),
    ("Bremse 20/35 weich", lambda: bremse((0.20, 0.35), (1.0, 0.5, 0.25))),
    ("Bremse 25/40/55 hart", lambda: bremse((0.25, 0.40, 0.55), (1.0, 0.5, 0.25, 0.0))),
    ("Ratsche 50 % bei neuem Hoch", lambda: ratsche(0.50)),
    ("Ratsche 80 % bei neuem Hoch", lambda: ratsche(0.80)),
    ("progressiv (Gegenprobe)", lambda: progressiv),
]
