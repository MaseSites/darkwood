"""Schwellenvergleiche, die nicht vom letzten Bit entschieden werden.

**Der Fehler, den dieses Modul behebt.** Setup A konstruiert sein Ziel als
``target = close + 1.5 * risk * side.sign`` (``strategy/setups.py:202``, Faktor
``BREAKOUT_FIRST_TARGET_R`` aus dem Video: „Erstes Ziel bei 1,5R"). Die
Mindesthürde in ``config/risk.yaml`` ist ``min_reward_risk: 1.5`` -- *dieselbe
Zahl*. Mathematisch ist das Chance-Risiko dieses Setups also exakt die
Schwelle, und ``>=`` wäre erfüllt.

In Gleitkomma ist es das nicht. ``close + 1.5*risk`` addiert einen winzigen
Betrag auf einen grossen Preis, Bits fallen weg; die anschliessende Subtraktion
holt sie nicht zurück (Auslöschung), und die Division verteilt den Rest. Über
die 36.155 gespeicherten A-Signale gemessen:

======================  =======
exakt 1.5                18.579
knapp darüber             8.756
knapp darunter            8.820
echt darunter (>1e-12)        0
======================  =======

**Null.** Kein einziges A-Signal liegt wirklich unter der Hürde. Die 8.820
Ablehnungen waren vollständig Rundungsrauschen, und weil der beabsichtigte Wert
*auf* der Schwelle liegt, ist der Fehler **einseitig**: er kann nur fälschlich
ablehnen, nie fälschlich durchlassen. Das Tor war für das grösste Setup des
Systems keine Regel, sondern eine zufällige 24-%-Ausdünnung.

**Was die Behebung kostet, ehrlich.** Von den durchgelassenen Zwillingen
sterben 81,66 % unmittelbar danach am Kostentor; nur 18,33 % werden ein Trade.
Die Behebung bringt also rund 1.193 zusätzliche Trades auf 7.349 bestehende
(+16,2 %) -- nicht 8.820. Und Setup A liegt über 3.529 Replay-Trades bei
**-0,0137 R** je Trade, 95 % [-0,0478, +0,0260] (nach Markt geclustert). Die
Zusatztrades kosten erwartet **-16,3 R**. Das ist eine Korrektheits-Behebung,
**keine Ertragsverbesserung**, und sie wird auch nicht als eine verkauft.

Warum sie trotzdem richtig ist: eine zufällige 24-%-Ausdünnung des grössten
Setups ist Rauschen im Messgerät. Die Effekte, die dieses Projekt sucht, liegen
knapp über der Auflösungsgrenze des Prüfstands -- da darf das Gerät nicht
selbst würfeln.

**Warum eine eigene Datei.** ``strategies/widen_stop.py:77`` berechnet den Stop
*gegen* ``max_cost_fraction_of_risk``, konstruiert den Wert also ebenfalls auf
eine Schwelle hin. Wird diese Strategie je eingeschaltet, erbt das Kostentor
exakt denselben Fehler aus exakt demselben Grund. Dann steht das Werkzeug
bereit und die Begründung daneben. (Gemessen ist das Kostentor heute sauber:
0 von 43.213 Zeilen liegen näher als 1e-9 am Deckel.)
"""

from __future__ import annotations

#: Wie nah an der Schwelle noch als „auf der Schwelle" gilt, relativ.
#:
#: Die grösste gemessene Abweichung über alle 36.155 A-Signale ist 2,78e-13
#: absolut auf 1,5, also rund 1,9e-13 relativ -- etwa 1.563 ULP. 1e-9 liegt
#: gut vier Grössenordnungen darüber und zugleich weit unter allem, was
#: wirtschaftlich einen Unterschied macht: ein Chance-Risiko von 1,4999999985
#: statt 1,5 ist keine Unterscheidung, die irgendjemand beabsichtigt.
#:
#: Bewusst relativ und nicht absolut. Eine feste Konstante wäre für ein
#: Chance-Risiko von 1,5 passend und für einen Kostenanteil von 0,08 um den
#: Faktor 19 zu grob.
TOLERANZ = 1e-9


def unterschreitet(wert: float, schwelle: float, *, toleranz: float = TOLERANZ) -> bool:
    """``wert < schwelle``, aber ein Treffer AUF der Schwelle zählt nicht als darunter.

    Ersetzt den nackten ``<``-Vergleich dort, wo der geprüfte Wert durch
    Subtraktion und Division naher Zahlen entsteht -- dort ist die letzte
    Stelle Rauschen und darf nicht entscheiden.

    Der Vergleich bleibt strikt: ein Wert, der *wirklich* unter der Schwelle
    liegt, wird weiterhin abgelehnt. Nur das Rauschband um die Schwelle wird
    der erlaubten Seite zugeschlagen -- und zwar der Seite, die die Absicht
    des Aufrufers ist, denn eine Schwelle wird formuliert, um ein Erreichen
    zuzulassen.
    """
    return wert < schwelle - abs(schwelle) * toleranz


def ueberschreitet(wert: float, schwelle: float, *, toleranz: float = TOLERANZ) -> bool:
    """``wert > schwelle``, mit demselben Rauschband auf der erlaubten Seite.

    Das Gegenstück für Obergrenzen (Kostendeckel, Hebeldecke). Heute benutzt
    es niemand -- das Kostentor prüft ``<=`` und ist gemessen sauber. Es steht
    hier, damit die Behebung vollständig ist statt halb: wer die eine Richtung
    braucht, braucht irgendwann die andere, und dann soll er sie nicht neu
    erfinden und dabei das Vorzeichen verdrehen.
    """
    return wert > schwelle + abs(schwelle) * toleranz
