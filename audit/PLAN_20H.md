# Plan für zwanzig Stunden: nach draussen schauen

Angelegt 11.10.2026. Auftrag von Severin, wörtlich im entscheidenden Teil:
*„falls du der Meinung bist, dass es so nicht funktioniert, dann gehe ins
Internet, durchsuche das komplette Internet und finde neue Informationen, wie
man richtig tradet."*

Ich bin dieser Meinung, und zwar gemessen. Also wird das der Plan.

---

## Was vorher richtiggestellt werden musste

**Die +54 USDT sind nicht verdient.** Sie sind unrealisierter Buchgewinn auf
vier offenen Shorts. Realisiert über 21 geschlossene Trades: **−0,76 USDT**.
Mit zehnfacher Grösse wären daraus **−7,56** geworden, nicht +500.

**Und 760 CHF Einsatz bei 10× Hebel sind 10 % Risiko je Trade**, nicht „mehr
Gewinn". Gemessen am Median-Stop von 1,31 %:

| Risiko je Trade | Konto nach den sieben Verlusten | nötig zum Aufholen |
|---|---|---|
| 1 % (heute) | 93,2 % | +7,3 % |
| 3 % (harter Deckel in `risk.yaml`) | 80,8 % | +23,8 % |
| **10 %** | **47,8 %** | **+109 %** |

Grösse multipliziert die Erwartung. Die gemessene Erwartung ist negativ
(−0,0906 R über 2 734 Replay-Trades, Rest neben der Marktrichtung −0,20 R über
die 21 Live-Trades). Eine negative Zahl mal zehn ist eine grössere negative
Zahl. Das ist keine Vorsicht, das ist Arithmetik.

**Darum wird der Risiko-Deckel nicht angefasst.** Nicht, weil ich zögere,
sondern weil es die eine Änderung ist, von der sicher ist, dass sie schadet.

---

## Warum nach draussen und nicht noch eine Variante von innen

24 Experimentfamilien sind abgeschlossen, keine hat einen Kandidaten ergeben.
Das sind keine Versuche „derselben Sache": Einstiegsregeln, Ausstiegsregeln,
Kostenfilter, Querschnitt, Carry, Orderfluss, maschinelles Lernen,
Ausführung, Hebel, Stop-Weite, Trade-Zahl, Zeitebenen, Haltedauer. Jede ist
mit beiden Toren gemessen.

**Was dabei nie geprüft wurde: ob die Grundannahme stimmt.** Das System sucht
Struktur-Setups auf Krypto-Perpetuals im Stunden- bis Tagesbereich. Dass *in
dieser Nische* ein Vorteil zu holen ist, hat hier nie jemand belegt — es war
die Ausgangsannahme.

Die Frage für die nächsten zwanzig Stunden ist deshalb nicht „welcher Filter
noch", sondern:

> **Welche Handelsansätze haben belegbare, ausserhalb der Stichprobe
> geprüfte Evidenz — und welche davon sind mit den Daten, die wir haben,
> überhaupt testbar?**

---

## Die Regeln für diesen Block

Dieselben wie bisher, und sie gelten gerade jetzt:

1. **Kein Echtgeld, keine Order, keine Broker-Anbindung.**
2. **Risiko-Deckel unberührt.** 1 % bis Kalibrierung belegt, 3 % hart.
3. **Kein API-Budget ausgeben.**
4. **Den Papierhandel nicht anfassen.** Er ist die einzige wachsende Evidenz,
   und die Frage entscheidet sich bei 45–62 Trades, also um den 20.–27.10.
5. **Jede neue Vergleichszelle vorher anmelden**, mit Zellen und
   Abnahmekriterium, vor dem ersten Lauf.
6. **Beide Tore bleiben:** korrigiertes Intervall ohne Null *und*
   Replikation 0,5–2,0×.
7. **Nichts aus den letzten sieben Trades ableiten.** Auswahl nach dem
   jüngsten Ergebnis ist die Methode, mit der sich dieses Projekt schon
   mehrfach selbst einen Vorteil vorgerechnet hat.

## Die Phasen

**Phase A — Literatur, breit.** Was hat dokumentierte, out-of-sample geprüfte
Evidenz? Nach Familien getrennt gesucht, nicht als eine Suche. Jede Quelle mit
Datum, Methode und der Frage: wurde das nach Veröffentlichung noch getestet?

**Phase B — Filter auf Testbarkeit.** Für jeden Fund: brauchen wir Daten, die
wir nicht haben? Ein Ansatz, der ein Instrument oder eine Datenreihe verlangt,
die hier nicht beschaffbar ist, wird als blockiert notiert und nicht
weiterverfolgt.

**Phase C — Anmelden und messen.** Die aussichtsreichsten als Zellen in
`audit/EXPERIMENTS_NEXT.yaml`, `total_comparisons` entsprechend erhöhen, dann
rechnen.

**Phase D — Ehrlich berichten.** Auch und gerade, wenn nichts übrig bleibt.

## Protokoll

*(wird fortgeschrieben)*
