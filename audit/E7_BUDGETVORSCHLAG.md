# E7: die Latte für ein bezahltes LLM-Urteil, und was es kostet

**Kein Experiment, ein Budgetvorschlag.** Der Forschungsauftrag verlangt
genau das: *„Kostenpflichtige Daten und API-Aufrufe als Budgetvorschlag mit
Nutzen/Kosten berichten; keine Käufe aus diesem Auftrag ableiten."* Ich gebe
autonom kein API-Budget aus.

---

## 1. Was die Abnahme verlangt, und warum das die Frage verschiebt

E7s Abnahme steht im Register und ist streng:

> Das Urteil muss **(a)** E7.2 (FakeBrain, arithmetisch und **kostenlos**) auf
> derselben Kandidatenmenge schlagen — nicht den ungefilterten Pool, denn
> FakeBrain ist der günstigere Massstab — und **(b)** absolut netto positiv
> sein.

Das ist der entscheidende Satz. Die Frage ist nicht „hilft ein LLM-Urteil",
sondern **„hilft es mehr als kostenlose Arithmetik"** — und, weil die Kosten
in die Nettorechnung zählen, „hilft es genug, um seinen Preis zu tragen".

## 2. Die Latte, aus vorhandenen Messungen

Drei Messungen dieses Projekts legen sie fest, ohne einen weiteren Lauf:

**Die gespeicherte Bewertung trägt nichts.** `scripts/study_calibration.py`:
roh ist `rating/100` stark überzuversichtlich (im Band 0,90–1,00 sagt sie
0,946 und beobachtet 0,373 auf 166 Fällen), und **kalibriert ist sie von der
Basisquote nicht zu trennen** — gepaart −0,00005 mit [−0,00011; +0,00001].

Diese Zahl ist nicht FakeBrains, sondern die des deterministischen
Mehrebenen-Scores (`rate(score_at(...))`). FakeBrain bewertet dieselben fünf
Faktoren per Regel. Dass eine regelbasierte Faktorsumme auf denselben Daten
mehr Trennschärfe hätte als der Score, ist möglich — und unbelegt.

**Kleine ML-Modelle auf denselben Kandidaten: nicht belegt.** E1.4
(logistische Regression) −0,1024 R mit [−0,1715; −0,0412] und E1.5 (flaches
LightGBM) −0,0673 R mit [−0,1511; +0,0324], beide gegen einen Zufallsfilter
gleicher Selektivität bei −0,1328 R. Besser als der Pool, keiner absolut
positiv.

**Selektion schlägt Zufall, verdient aber nichts.** Das ist der Stand, den
E7.4 überbieten müsste: nicht „besser als nichts", sondern **absolut netto
positiv** — und besser als eine kostenlose Arithmetik, die selbst schon
besser als Zufall ist.

## 3. Was es kostet

Bestätigungsfenster aus der eingefrorenen E1-Menge: **13 704 Entscheidungen**
(davon 3 939 genommen). Ein Urteil je Entscheidung, Preise je Million Token.

**Die Token-Zahlen sind geschätzt, nicht gemessen** — aus der Struktur des
normalisierten Snapshots (MTF-Ebenen, benannte Level, Faktor-Schema), nicht
aus einem Lauf. Darum drei Grössen statt einer.

| Snapshot | Opus | Sonnet | Haiku |
|---|---|---|---|
| schlank (2 500 / 400) | 925 USD | 185 USD | **49 USD** |
| mittel (5 000 / 600) | 1 644 USD | 329 USD | 88 USD |
| reich (9 000 / 800) | **2 672 USD** | 534 USD | 143 USD |

**Und jetzt die Zahl, die zählt.** Das Konto hat **1 000 CHF**. Also kostet
*eine* Messung zwischen **5 % und 267 % des gesamten Kapitals.**

Der Auftrag sagt es selbst, für einen viel kleineren Posten: *„Bei kleinen
Portfolios ist selbst ein monatlicher Fixbetrag materiell: 50 CHF × 6 = 300
CHF, also 30 % des Startkapitals."* Opus auf dem vollen Fenster ist das
Fünf- bis Neunfache davon, für einen einzigen Lauf.

### Was den Preis senkt, und was es kostet

* **Die Batch-API halbiert ihn.** Der Backtest-Pfad ist ohnehin asynchron, also
  ist das kein Kompromiss. Opus/mittel fällt damit auf ~822 USD.
* **Ein Caching-Treffer senkt den Eingabeanteil erheblich.** Normalisierte
  Snapshots sind ähnlich, also ist die Trefferquote plausibel hoch — aber
  unbelegt, solange `usage.cache_read_input_tokens` nicht gemessen ist.
* **Eine Stichprobe statt des ganzen Fensters** senkt linear und kostet
  Trennschärfe. Bei 2 000 Entscheidungen statt 13 704: Opus/mittel ~240 USD.
  Ob 2 000 reichen, hängt am Effekt, den man suchen will — und der ist nach
  Abschnitt 2 klein.

## 4. Die Empfehlung, und sie ist unbequem

**Nicht jetzt kaufen.** Drei Gründe, in dieser Reihenfolge:

1. **Die Latte liegt dort, wo nichts hinreicht.** E7.4 müsste absolut netto
   positiv sein. Kein Arm in 21 gemessenen Familien ist das. Ein Urteil, das
   diese Hürde nimmt, wäre der erste — und die Kalibrierungsmessung sagt
   nichts voraus, was in diese Richtung zeigt.
2. **Der Preis ist mit dem Kapital vergleichbar.** Eine Messung, die 5 bis
   267 % des Kontos kostet, muss nicht bloss etwas finden, sondern genug,
   um sich selbst zu bezahlen. Das ist eine andere Schwelle als
   „statistisch signifikant".
3. **Es gibt einen kostenlosen Vorlauf, der noch nicht gelaufen ist.**
   E7.1 bis E7.3 kosten nichts, und sie beantworten die Vorfrage: *trägt
   die regelbasierte Faktorsumme überhaupt mehr als der Score, dessen
   Trennschärfe gemessen null ist?* Fällt das negativ aus, ist E7.4 eine
   teure Wiederholung.

**Was ich stattdessen vorschlage, wenn der Arm gewollt ist:** Haiku auf einem
schlanken Snapshot, über die Batch-API, auf einer Stichprobe — rund **25
USD**. Das beantwortet nicht E7, aber es misst die Token-Zahlen, die oben
geschätzt sind, und die Cache-Trefferquote. Danach ist die Kostenseite
gemessen statt geraten, und die Entscheidung über den grossen Lauf steht auf
Zahlen.

## 5. Was dieser Bericht nicht ist

Keine Messung von E7. Die freien Arme E7.1–E7.3 brauchen einen Harness über
Snapshots, den es noch nicht gibt; ihn zu bauen war in diesem Fenster der
schlechtere Einsatz gegen eine laufende, zeitkritische Aufnahme, und das ist
eine Abwägung und keine Erledigung. E7 bleibt im Register **registriert**.
