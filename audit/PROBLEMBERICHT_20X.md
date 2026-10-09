# Trading Brain — vollständiger Problembericht

**Stand 09.10.2026, 00:12 Uhr lokal / 08.10. 22:12 UTC.**
Zweck: Weitergabe. Hier stehen **Probleme, keine Lösungen** — ausdrücklich so
bestellt. Jede Zahl ist gemessen und reproduzierbar; wo eine Zahl unsicher
ist, steht ihr Intervall daneben.

**Frage, die zu lösen ist:** aus **1 000 CHF** in **sechs Monaten 20 000 CHF**
mit echtem Geld.

---

## 0. Kurzfassung in sechs Zeilen

1. Das System läuft technisch vollständig und seit Tagen ohne Ausfall.
2. **22 Strategie-Familien sind gemessen. Keine ist positiv.**
3. Der Vorwärtslauf steht bei +0,68 R je Trade — und ist gemessen **Hebel auf
   die Marktrichtung**, nicht eigene Leistung (Beta 1,79, Rest +0,005 R).
4. Das Ziel braucht **+0,055 R je Trade** im günstigsten Fall. Gemessen sind
   **−0,09 R**. Die Lücke ist **0,145 R je Trade**.
5. Aus der gemessenen Verteilung erreicht das Ziel in 40 000 Simulationen
   **0,00 %** — und bei 3 % Risiko endet fast die Hälfte im Ruin.
6. **Was fehlt, ist kein Werkzeug und keine Datenquelle. Es fehlt ein Vorteil.**

---

## 1. Was das System ist

Ein Forschungsmotor für Krypto-Perpetuals. Ein LLM ist ausschliesslich
Interpretations- und Entscheidungsschicht, nie Datenquelle und nie Executor.

```
MARKTDATEN (Binance USD-M, öffentlich)
   ↓
ANALYSE        8 Indikatoren, Struktur, Liquidität, Regime, Level
   ↓           Multi-Timeframe W1/D1/H4/H1/M15, M1 nur zur Intrabar-Auflösung
SNAPSHOT       ATR-normalisiert, ohne absolute Preise, ohne Datum, ohne Symbolname
   ↓
BEWERTUNG      7 Faktorfamilien, gewichtete Summe in Python (nicht im LLM)
   ↓
RISIKO         Risikobudget → Positionsgrösse → Hebel, in dieser Reihenfolge
   ↓
SIMULATOR      Fills, Gaps, Gebühren, Funding, Liquidation auf Mark-Price
   ↓
PAPIERHANDEL   12 Konten à 1 000, vorwärts, Entscheidung vor dem Ergebnis
   ↓
JOURNAL        2 749 Trades, jede Begründung vor dem Ausgang auf Platte
```

**Was live läuft, Stand jetzt:** der Papierhändler über 12 Märkte (BTC, ETH,
SOL, XRP, ADA, AVAX, LINK, DOGE, BNB, LTC, DOT, ATOM), 39 636 Zyklen, letzte
verarbeitete Minute 22:11 UTC bei 22:12 — also aktuell.

**Was es nicht kann:** echte Orders. Kein Codepfad von der Entscheidungs-
schicht zu einer Börse. Eine echte Order bräuchte einen server-seitig
ausgestellten Einmal-Token nach einer **1,2 Sekunden gehaltenen menschlichen
Bestätigung**.

## 2. Wie es läuft — der aktuelle Stand

| | |
|---|---|
| Papierkonto | **12 114,66 USDT** (+114,66 seit Umstellung auf 12 Konten) |
| Offene Positionen | 5 |
| Vorgeschlagen / eröffnet / geschlossen | 106 / 19 / 14 |
| **Von der Risk Engine abgelehnt** | **87 von 106 (82 %)** |
| Unbefüllt verfallen | 0 |
| Fehlgeschlagene Zyklen | 1 977 (Netz, ohne Datenverlust) |
| Journal | 2 734 Replay + 15 vorwärts |

### Die 15 Vorwärtstrades, vollständig

| Datum | Markt | Seite | Ausgang | R | netto |
|---|---|---|---|---|---|
| 02.10. 12:30 | BTC | short | stop | −1,1045 | −55,05 |
| 03.10. 17:07 | BNB | long | target | +1,3988 | +6,99 |
| 03.10. 19:16 | LINK | short | stop | −1,1206 | −5,60 |
| 04.10. 06:48 | ATOM | short | stop | −0,7772 | −3,89 |
| 04.10. 15:05 | ATOM | long | stop | −1,1379 | −11,33 |
| 04.10. 16:17 | LTC | long | stop | −1,0778 | −10,78 |
| 05.10. 14:51 | LINK | short | target | +1,4691 | +14,61 |
| 05.10. 20:32 | ATOM | long | target | +1,4511 | +14,29 |
| 07.10. 02:00 | LINK | short | target | +1,9773 | +19,95 |
| 07.10. 02:01 | DOGE | short | target | +2,2541 | +22,54 |
| 08.10. 04:19 | LTC | short | target | +1,9789 | +19,58 |
| 08.10. 15:13 | ADA | short | target | +1,9771 | +19,77 |
| 08.10. 15:15 | DOT | short | target | +1,9701 | +19,70 |
| 08.10. 15:20 | SOL | short | target | +1,9737 | +19,73 |
| 08.10. 20:28 | DOT | short | stop | −1,0665 | −10,87 |

**Mittel +0,6777 R, Intervall [−0,3610; +1,6528] — spannt über die Null.**
Short: 11 Trades, +0,8665 R, netto +60,45. Long: 4 Trades, +0,1586 R, netto
−0,83.

## 3. Die Ziel-Arithmetik

20× in 182 Tagen heisst **4,32 Verdoppelungen**, also **+1,66 % pro Tag** oder
**+63,85 % pro Monat**, ohne Unterbrechung, sechs Monate lang.

Umgerechnet auf das, was ein einzelner Trade liefern muss:

| Trades/Tag | Trades total | nötig je Trade | bei 1 % Risiko | bei 3 % Risiko |
|---|---|---|---|---|
| 1,9 (gemessene Rate) | 346 | +0,8701 % | **+0,8701 R** | +0,2900 R |
| 3,0 | 546 | +0,5502 % | +0,5502 R | +0,1834 R |
| 10,0 | 1 820 | +0,1647 % | +0,1647 R | **+0,0549 R** |

**Die günstigste Zelle der ganzen Tabelle verlangt +0,0549 R je Trade.**

Dagegen, gemessen:

| | R je Trade |
|---|---|
| Replay, 2 734 Trades | **−0,0906** |
| Bester je gefundener Arm („Champion") | **−0,0340** |
| E8: Rest nach Abzug der Marktbewegung | **−0,0823** [−0,1414; −0,0119] |

**Die Lücke beträgt 0,089 bis 0,145 R je Trade.** Das ist die ganze Aufgabe,
in einer Zahl.

## 4. Was die gemessene Verteilung über 182 Tage tut

40 000 Simulationen, Trades gezogen aus den **echten 2 734** Journal-Trades,
geometrisch wie ein Konto wirklich wächst:

| Trades/Tag | Risiko | Ziel am Ende | Ziel je berührt | **Ruin** | Median Ende |
|---|---|---|---|---|---|
| 3 | 1 % | 0,00 % | 0,00 % | 0,00 % | 575 CHF |
| 3 | 3 % | 0,00 % | 0,00 % | **44,16 %** | 139 CHF |
| 10 | 1 % | 0,00 % | 0,00 % | 25,51 % | 159 CHF |
| 10 | 3 % | 0,00 % | 0,00 % | **99,56 %** | 1 CHF |

**Nicht eine von 160 000 Simulationen erreicht 20 000 CHF.** Mehr Hebel und
mehr Trades machen es nicht besser, sondern schneller schlimmer: bei
negativer Erwartung ist mehr Risiko kein Beschleuniger, sondern ein
Verstärker in die falsche Richtung.

### Und warum die +0,68 R des Vorwärtslaufs nichts retten

Dieselbe Simulation, gezogen aus den **15** Vorwärtstrades:

| | |
|---|---|
| Ziel erreicht | **100,00 %** |
| Median Endkapital | **36 590 382 CHF** |

**36 Millionen.** Diese Zeile ist kein Ergebnis, sie ist der Beweis, dass man
aus 15 Trades nicht extrapolieren darf. Jede Hochrechnung aus dem
Vorwärtslauf erzeugt Zahlen dieser Art, und das Intervall der 15 Trades
spannt ohnehin über die Null.

---

# 5. DIE PROBLEME

## 5.1 Das Kernproblem: es gibt keinen gemessenen Vorteil

**P1 — 22 Familien gemessen, keine positiv.** 124 registrierte Versuche, 87
verschiedene Arme, 21 Familien abgeschlossen, 1 nicht testbar. Der beste je
gefundene Arm hat **−0,0340 R**.

**P2 — Die Einstiege tragen keinen Vorteil, auch brutto nicht.** Die
Brutto-Erwartung der genommenen Population spannt über die Null
(+0,0080 R [−0,022; +0,039]). Der Verlust ist die Maut, nicht die Richtung.

**P3 — Das System ist gemessen gehebeltes Marktbeta ohne eigenen Beitrag.**
E8: Beta zum Kryptomarkt **+0,985** [+0,873; +1,105] über 2 748 Trades, Rest
daneben **−0,0823 R** mit Intervall ohne Null. Vorwärts: Beta **+1,788**, Rest
**+0,0048 R**. Die 44 Trades bis Ende Oktober tragen rechnerisch 3,6 R Maut
und keinen eigenen Beitrag.

**P4 — Richtungsvorhersage ist gemessen nicht vorhanden.** 35 Merkmale in zwei
Familien ordnen BTCs nächste 5–10 Stunden mit Korrelation **0,004**. Ein
Vorwärts-Score findet nichts.

**P5 — Auswahl unter den Signalen hilft nicht.** Meta-Labeling auf 42 849
gelabelten Kandidaten: beide Modelle schlagen einen Zufallsfilter — es gibt
also Auswahlsignal — und bleiben **absolut negativ** (−0,1052 und −0,0908 R).

**P6 — Die Trefferquote ist ein irreführendes Ziel.** Zwei Messungen fanden
Populationen mit *höherer* Trefferquote, die *weniger* verdienen.

**P7 — Ausgänge sind ausgereizt.** E3, 7 255 Fälle gepaart auf identischen
Einstiegen: die bestehende Politik (Stop + Ziel) schlägt beide Alternativen.
24-Stunden-Uhr −0,0619 R schlechter, 2-ATR-Trail −0,0557 R **zuverlässig**
schlechter. Es gibt hier nichts zu optimieren.

**P8 — Der Carry war ein Ertrag und ist keiner mehr.** E6: die Basis ist nicht
das Problem (±0,002 % über 30 Tage), die Maut ist es (0,280 % je Runde gegen
0,2–0,5 % Funding in 30 Tagen). Bei 180 Tagen Haltedauer passierte er erstmals
Tor 1 (+1,5554 % [+0,2405; +3,0046]) und fiel dann an Tor 2 mit gekipptem
Vorzeichen (−0,04×). Ab 18.11.2024 bei keiner Haltedauer positiv, bei 30 Tagen
zuverlässig negativ.

**P9 — FreqAI verschlechtert, statt zu verbessern.** Baseline 15 624 Trades,
−0,58 % je Trade, 526 Verlusttage von 579, Profit-Faktor 0,35. FreqAI
darauf: Erwartung −0,47 gegen −0,37 R, also **25,8 % schlechter je Trade** —
bei 54,7 % Trefferquote.

## 5.2 Kostenprobleme

**P10 — Die Maut ist grösser als der Vorsprung.** Über die volle Historie
(15 624 Trades) ist der Einstiegsvorsprung **3,8× kleiner** als eine
Maker/Maker-Runde. Gebühren senken kann das Vorzeichen deshalb nicht drehen,
solange der Vorsprung selbst null ist.

**P11 — Die Venue, die billiger wäre, ist unklar billiger.** Auf der
alternativen Venue kostet eine Taker-Runde auf BTC 0,05 bp gegen eine
Obergrenze des Einstiegsvorsprungs von 1,06 bp — Faktor 21. Nach Abzug der
gemessenen Taker-Drift (+0,086 bp bei 1 s, Intervall ohne Null) bleibt Faktor
**4,8×** — **wenn** die Drift permanent ist. Sie revertiert aber: bei 30 s
spannt ihr Intervall, bei 5 min kippt es. **Beide Lesarten stehen, keine ist
belegt.**

**P12 — Die 1,06 bp sind selbst eine Obergrenze.** Sie sind die obere Grenze
der einzigen von vier Zellen mit Intervall ohne Null. Wer den Faktor zitiert,
stellt eine Obergrenze gegen eine Untergrenze.

**P13 — Market Making auf der günstigen Venue ist keine Strategie für dieses
Kapital.** Der Maker-Vorteil ist gemessen (−0,083 bp bei 1 s auf 12 184
belegten Fills), aber: 0,0017 CHF je Fill. Für 2 953 CHF bräuchte es **1,78
Millionen Fills** bei 8,3 % Füllquote, also **21,4 Millionen gestellte
Orders**. Dazu Quotierung unter 300 ms Storno-Latenz — unvereinbar mit der
1,2-Sekunden-Bestätigung.

**P14 — Liquid Co-Invest ist als Venue teurer, nicht billiger.** Krypto-Perps
Tier 0: Taker 0,095 %, Maker 0,065 % — das 1,7- bzw. **3,25-fache** der im
Simulator angesetzten Binance-Raten. Eine Maker-Runde kostet dort 0,13 % statt
0,04 %.

## 5.3 Datenprobleme

**P15 — Quellen schreiben ihre Historie um.** Gleicher Code, gleicher
Zeitraum, anderes Panel. Darum trägt jedes Panel jetzt einen `vintage_id` —
aber der Effekt selbst ist nicht wegzukriegen. Der Zukunfts-Mutationstest ist
**blind** dagegen: er variiert die Zukunft, nicht die Vergangenheit einer
Quelle.

**P16 — Der Funding-Ordner mischt zwei Börsen.** 4 Märkte Bybit, 8 Binance.
Auf dem gemeinsamen Kalenderfenster fällt der Befund in 11 von 12 Märkten —
er überlebt, aber zwölf korrelierte Märkte sind **eine** Beobachtung eines
gemeinsamen Trends, nicht zwölf.

**P17 — Eine abgetastete Auswahl repliziert hier nicht.** Vier Grössen auf
voller 11-Stunden-Aufnahme neu gemessen:

| Grösse | kurz | voll | Verhältnis | Basis |
|---|---|---|---|---|
| Falschfüllung | 0,6 % | 0,6 % | 1,00× | ganzes Tape |
| Taker-Drift | +0,078 bp | +0,086 bp | 1,10× | ganzes Tape |
| **Maker-Markout** | −0,195 bp | −0,083 bp | **0,43×** | abgetastetes Buch |
| **Niveau-Differenz** | +0,342 bp | **−0,504 bp** | **Vorzeichen** | abgetastete Zellen |

**P18 — Die Aufnahme ist unvollständig und die Lücke ist auf der neuen Venue
nicht zählbar.** `trade_id` läuft dort global über alle Märkte, also kann eine
Lücke nur als *Ereignis* berichtet werden (334 von 11 163 Abfragen = 3,0 %),
nie als Trade-Zahl.

**P19 — Es gibt keinen Streaming-Collector.** Alles ist Polling. Damit ist E5
(Orderflow auf handelbarem Horizont) blockiert, und die beobachtete
Lead-Lag-Asymmetrie nicht auflösbar — siehe P26.

**P20 — Die gespeicherte Minutenreihe hat Löcher, wo nur der Papierhändler
schreibt.** Acht Lücken in BTC-M15 seit dem 01.10., weil der Papierhändler je
Zyklus nur wenige Kerzen holt. Beim Nachladen springt `resume=True` auf die
neueste Kerze, füllt **kein** Loch und meldet Erfolg.

## 5.4 Mess- und Beweisprobleme

**P21 — Nur 15 Vorwärtstrades, und sie entstehen langsam.** ~1,9 Trades/Tag.
100 Vorwärtstrades brauchen etwa **52 Tage**. Das ist der harte Takt jeder
echten Evidenz, und er lässt sich nicht beschleunigen, ohne die Frage zu
ändern.

**P22 — Der Vorwärtslauf lief in einem einseitigen Markt.** LINK −13,4 %,
DOGE −12,2 %, ADA −6,0 %, BTC −4,4 % im Fenster. 11 von 15 Trades waren short,
und nur die Short-Seite verdiente (+0,8665 R gegen +0,1586 R).

**P23 — Das Prüffenster ist unberührt und muss es bleiben.** 0 Konsultationen.
Es gibt derzeit keinen Kandidaten, der die Konsultation wert wäre. Es
aufzubrauchen, ohne einen zu haben, verschiesst die einzige Munition.

**P24 — Die LLM-Zuversicht ist nicht kalibriert.** Rohe Bewertung massiv
überzuversichtlich (0,946 vorhergesagt gegen 0,373 beobachtet auf 166 Fällen).
Kalibriert ist sie von der Basisrate nicht unterscheidbar
(−0,00005 [−0,00011; +0,00001]). `calibration_proven` bleibt **false** — und
damit ist jedes Risikoband über 1 % gesperrt.

**P25 — Ein Backtest-Ergebnis ist eine Stichprobe, nicht eine Zahl.** Bei
LLM-Modellen ohne Sampling-Parameter ist der Decision-Cache die einzige
Reproduzierbarkeitsgarantie. Streuung über drei Läufe ist zu messen; ist sie
grösser als der Abstand zur Baseline, wurde nichts gemessen.

**P26 — Eine mögliche Vorlaufzeit ist nicht von einem Uhrenversatz zu
trennen.** Die Kreuzkorrelation der Sekundenrenditen hat ihr Maximum bei
Versatz null, aber Versatz −1 ist **3,4-mal** so gross wie +1, in beiden
Märkten (BTC 0,295 gegen 0,087; ETH 0,332 gegen 0,076). Das heisst entweder
„Binance läuft eine Sekunde voraus" **oder** „die Uhren der beiden Börsen
gehen eine Sekunde auseinander". Polling-Daten können das nicht trennen.
**Wäre es ein echter Vorlauf, wäre es die erste handelbare Grösse dieser
Untersuchung.**

## 5.5 Ausführungs- und Venue-Probleme

**P27 — Eine Maker-Order als gefüllt zu verbuchen ist auf dem echten Buch
falsch.** 91,4 % bis 96,6 % der beobachteten ruhenden Orders werden **belegt
storniert**, nicht gefüllt. Am Antritt (0–1 bp vom Mid) füllen nur **12,4 %**.

**P28 — 1 000 USD übersteigen bei manchen Märkten den ganzen Antritt.** Bei
XRP reicht die Grösse über die erste Bücherstufe hinaus; der Backtest nimmt
an, es gäbe sie.

**P29 — Die neue Venue ist nachweislich nur als Datenquelle abgesichert.**
Fehlt der technische Nachweis, dass ein Handelsschlüssel **keine Auszahlung**
erlaubt, bleibt sie ausschliesslich Datenquelle. Bei DEX-Signern ist ein
fehlender Auszahlungsknopf **kein** Nachweis.

**P30 — Liquids Füllmodell ist nicht dokumentiert.** Geprüft auf beiden
Doku-Seiten. Damit ist es als Referenz untauglich: ein Unterschied gegen eine
Blackbox sagt nur, dass zwei Modelle sich unterscheiden.

**P31 — Es gibt keinen programmatischen Weg von unserer Engine zu Liquid.**
Der Papierhändler ist ein Python-Prozess und kann kein MCP aufrufen. Liquids
Paper-Modus wird aus einer Chat-Sitzung bedient.

**P32 — Ein Connector, der Paper kann, kann auch Live.** Der Weg dazwischen
ist ein Satz im Chat. Die Bestätigung dort ist ein **Tap auf eine Karte**,
erzwungen von einer fremden Oberfläche, und der Orderweg läuft nicht durch
unser `execution/`.

## 5.6 Rechtliche und Kontoprobleme — **ungeklärt, blockierend**

**P33 — Eignung und Identität für Live-Handel sind ungeklärt.** Der
Zustandsbericht nennt einen minderjährigen Kontoinhaber, andere Angaben nennen
ein anderes Alter. **Das ist nicht aufgelöst, und bis es aufgelöst ist, ist
echter Handel nicht zu starten.** Keine Umgehung von Alters-, Länder- oder
Kontoregeln.

**P34 — Ein Handelsschlüssel darf keine Auszahlung erlauben**, und das muss
technisch nachweisbar sein, nicht zugesichert.

**P35 — Die Währung ist nicht geklärt.** Konten heissen CHF, alle Preise sind
USDT, **im ganzen Code existiert keine Umrechnung**. Eine echte Einzahlung
bräuchte CHF→USDT (Gebühr + Spread), und der Frankenkurs läuft danach
unabhängig weiter.

## 5.7 Risiko- und Ruinprobleme

**P36 — Bei negativer Erwartung ist Hebel ein Verstärker in die falsche
Richtung.** 3 % Risiko bei 10 Trades/Tag: **99,56 % Ruin** in der Simulation.

**P37 — Die harte Grenze von 3 % ist nicht das Problem, sondern der Schutz.**
Höhere Werte dürfen nur als Stressszenario im Simulator laufen.

**P38 — 1 000 CHF Startkapital kollidiert mit Mindestgrössen.** Die Venue
weigert sich unter rund 50 USDT Notional; Liquid verlangt mindestens 15 $
Collateral je Order. Bei 1 % Risiko von 1 000 CHF und einem 1 %-Stop ist die
Position 1 000 — tragbar, aber nach dem ersten Drawdown wird die Luft dünn.

**P39 — Die Verlustserie ist nicht das Hauptrisiko, die Erosion ist es.** Der
Median endet bei 575 CHF (3 Trades/Tag, 1 % Risiko) — ohne einen einzigen
dramatischen Tag. Nur Maut.

## 5.8 Betriebsprobleme

**P40 — Das Netz ist der häufigste Ausfall.** 1 977 fehlgeschlagene Zyklen;
in der Aufnahme zwei DNS-Ausfälle von 760 und 105 Minuten. Ohne
Stillstandserkennung bleibt das **zwölf Stunden** unbemerkt — einmal passiert.

**P41 — Ein einmal gemessener Takt ist eine Konstante, die verfällt.** Der
Binance-Collector stand auf 30 s, begründet mit 10,1 Trades/s. Gemessen wurden
später 27,7 und dann 35,1 — Abdeckung fiel auf **38,7 %**, und der Zähler
meldete bis dahin „keine Lücke".

**P42 — Ein Codepfad, dessen Auslöser länger ist als der Test, ist
ungetestet.** Ein Fortschrittsvermerk alle zehn Minuten tötete einen
11-Stunden-Lauf, nachdem drei grüne Rauchtests und grünes Lint ihn nie
erreicht hatten.

**P43 — Ein `print` ohne `flush` ist kein Protokoll.** Die
Abschlussmeldung des Papierhändlers war über ihre ganze Lebensdauer unsichtbar.

**P44 — Zwei Prozesse desselben Dienstes verdoppeln die Anfragerate.** Einmal
liefen zwei Papierhändler und erzeugten 58 fehlgeschlagene Zyklen am
Binance-Limit. `pkill -f` erreicht hier keine Windows-Prozesse.

**P45 — Quiver liefert für dieses System keine Daten.** 19 Tools, alle auf
SEC/FEC/Kongress/USAspending. `search_datasets("bitcoin")` → **0 Treffer**,
Kontrollabfrage `"insider"` → 4 Treffer, der Filter arbeitet also. Dazu: das
Konto ist authentifiziert, hat aber **kein aktives Abo** — alles oberhalb von
Tier 0 antwortet mit einer Abo-Aufforderung.

---

## 6. Was gemessen **NICHT** das Problem ist

Dieser Abschnitt ist der wertvollste für jeden, der Lösungen sucht: hier
stehen die Wege, die schon zugemauert sind.

| Nicht das Problem | Beleg |
|---|---|
| Die Risikoregeln | Alle **drei** Ablehnungsregeln über 12 Märkte / 41 382 Signale bestätigt, jede abgelehnte Population brutto-negativ mit Intervall ohne Null |
| Die Ausgänge | E3: bestehende Politik schlägt beide Alternativen, 2-ATR-Trail zuverlässig schlechter |
| Die Stop-Weite | Grösse und Hebel kürzen sich aus `net_r` heraus; der Stop verschiebt den Pfad, dreht aber das Vorzeichen nicht |
| Das Füllmodell | 0,6 % Falschfüllung auf 657 647 echten Orders; für unsere Einstiege unterscheiden sich Berührung und Durchhandeln auf **0,5 %** der Fälle |
| Die Basis beim Carry | ±0,002 % über 30 Tage, kehrt zurück — Hypothese geprüft und widerlegt |
| Die Trade-Anzahl | Ein Hebel, der nur die Anzahl ändert, kann das Vorzeichen nicht drehen |
| Günstigere Trades | Sind gemessen besser (+0,0561 R brutto, Intervall ohne Null) — und immer noch nicht positiv je Trade |
| Die Datenherkunft der Derivate | Aufgelöst: Bybit, exakt bis zur letzten Dezimale |
| Survivorship | Ein Point-in-Time-Universum IST baubar; echte Perp-Sterblichkeit **3,4 %**, nicht 8,1 % |
| Mehr Märkte | 12 korrelierte Krypto-Perps sind näher an einer Beobachtung als an zwölf |

## 7. Was offen ist

**O1** — E4 (marktbereinigte Relative-Value-Entscheidung): entsperrt,
**nicht gerechnet**.
**O2** — E5 (Orderflow auf handelbarem Horizont): **blockiert** an P19.
**O3** — E7 (LLM-Urteil als Shadow-Studie): nur als Budgetvorschlag registriert.
**O4** — E0 Punkt 3 (Signalübertragung zwischen Venues): braucht Signale aus
dem Aufnahmefenster; bei 1,9 Trades/Tag sind das über eine Nacht eine Handvoll.
**O5** — P26, die Lead-Lag-Asymmetrie. **Die einzige offene Grösse mit
möglicherweise positivem Vorzeichen.**
**O6** — Die Warteschlangenposition: ob eine *eigene* Order sich so verhält wie
die beobachteten fremden.

## 8. Nicht verhandelbar

Wer Lösungen vorschlägt, muss diese Grenzen einhalten — sie sind Teil des
Problems, nicht Verhandlungsmasse:

1. Echte Orders behalten die **1,2 Sekunden gehaltene menschliche
   Bestätigung**. Keine neue Venue-Anbindung umgeht sie.
2. Keine echten Orders oder Wallet-Transaktionen durch LLM oder MCP.
3. `testnet=False` und `allow_live=True` bleiben **unabhängige**
   Voraussetzungen.
4. **Harte Risikogrenze 3 % bleibt.** Höheres nur als Stressszenario im
   Simulator.
5. Kein Hebel als Ersatz für einen fehlenden Vorteil.
6. Handelsschlüssel ohne Auszahlungsrecht, technisch nachweisbar.
7. Keine Umgehung von Alters-, Länder- oder Kontoregeln. **P33 bleibt offen.**
8. Secrets nicht ins Repository. Tests ohne Produktionsdatenbank.
9. Kein Erfolgskriterium nach Kenntnis des Ergebnisses ändern. Beide Tore
   bleiben: korrigiertes Intervall ohne Null **und** Replikation 0,5–2,0×.
10. Keine Zahl ohne ihr Intervall. Kein einzelner Markt als Eigenschaft des
    Systems.

## 9. Die eine Frage, die zu lösen ist

Alles oben lässt sich auf einen Satz zusammenziehen:

> **Es gibt eine Lücke von 0,089 bis 0,145 R je Trade zwischen dem, was
> gemessen ist, und dem, was das Ziel verlangt — und 22 gemessene Familien
> haben sie nicht geschlossen.**

Was fehlt, ist **nicht**: eine Datenquelle, ein schnellerer Computer, mehr
Märkte, feinere Zeitebenen, bessere Ausgänge, weniger Gebühren, mehr Hebel
oder mehr Trades. Das ist alles gemessen.

Was fehlt, ist eine **Richtungs- oder Timing-Information, die das System heute
nicht hat** — und ein Beweis, dass sie nach Kosten übrig bleibt und in einem
zweiten Zeitfenster wieder auftaucht.

---

---

# 10. NACHTRAG 09.10.2026 — was sich seit diesem Bericht geändert hat

Der Bericht oben bleibt unverändert stehen. Was seitdem gemessen wurde, steht
hier — einschliesslich **vier Punkte, die widerlegt oder präzisiert sind.**

## 10.1 Widerlegt

**P38 war falsch** („1 000 CHF kollidiert mit Mindestgrössen"). Live an
`exchangeInfo` geprüft: die Position ist bei 1 % Risiko das 0,76-fache des
Eigenkapitals (764 USDT bei 1 000), das höchste effektive Minimum ist 82,39
(BTC), und der **Kontoboden liegt bei 108 USDT** — fast eine Grössenordnung
unter 1 000. Was stattdessen bindet: die **Körnung**. Auf BTC ist eine
Schrittweite 10,79 % der Position, das angestrebte Risiko also nur in
11-%-Schritten treffbar. Auf den anderen elf ≤ 3,45 %.
*(`audit/EXECUTION_COSTS.md`)*

**Die Füllfrage ist geschlossen** (P27 betraf Market Making, nicht unsere
Einstiege). 0,6 % Falschfüllung auf 657 647 echten Orders; und für unsere
Einstiege unterscheiden sich Berührung und Durchhandeln auf **0,5 %** der
Fälle. Das Füllmodell ist in keiner gemessenen Grösse eine wesentliche
Fehlerquelle. *(`audit/E9_FUELL_REALISMUS.md`)*

## 10.2 Präzisiert

**P19/P26 — der Blocker ist nicht „es gibt keinen Collector".** Gemessen:
REST funktioniert, DNS löst, der WebSocket-Handshake gelingt, `SUBSCRIBE`
wird mit `{"result":null,"id":1}` bestätigt — und dann kommen **null**
Marktnachrichten in 12 s gegen rund 95 fällige. Vier Pfade geprüft. Und der
Host, der *liefert* (`stream.binancefuture.com`), hat Preise **auf den Cent**
richtig und einen Kennraum um **Faktor 11** daneben, bei einem Sechstel der
Rate. Eine Preisprüfung hätte das nie gefunden. **Es ist kein Bauproblem.**
*(`audit/E5_ORDERFLOW.md`)*

**E4 war zu früh entsperrt** — meine eigene Fehleinschätzung. Die
Punkt-in-Zeit-Tabelle nennt, *welche* Symbole wann handelbar waren, nicht
deren Kurse: 749 handelbare Perps am 01.06.2026, Kurse auf der Platte für
**zwölf**. *(`audit/E4V_RELATIVE_VALUE_VORPRUEFUNG.md`)*

## 10.3 Neu gemessen

| | |
|---|---|
| **E10** Stop-Auslöser | gepaart −0,0064 R [−0,0297; +0,0161], beide Tore verfehlt. Und der schlimmste Einzelverlust wächst von −1,890 auf **−6,841 R** |
| **E4V** Querschnitt täglich | −12,43 bp/Tag [−23,40; −1,35], Null ausgeschlossen *auf der falschen Seite*; **beide Vorzeichen verlieren** nach Kosten |
| **E4W** Querschnitt wöchentlich | Maut fällt um Faktor 5, Brutto **nicht** — und doch **nicht entscheidbar**: 31,9 Jahre nötig, 6,1 vorhanden |
| **Trial-Ledger** | die behaupteten 124 Versuche sind jetzt zu 112 belegt (59 nachrechenbar aus gespeicherten R-Reihen), **12 ohne Beleg** statt 110 |
| **unabhängige Bestätigung** | von 59 neu gerechneten Zellen der früheren Suche: **0 mit Intervall ohne Null**, beste +0,0455 R |

## 10.4 Ein Defekt in der Statistik, und er betraf ein Urteil

Bei 3 000 Bootstrap-Ziehungen liegen unter dem korrigierten Perzentil **1,44
Ziehungen** — die Grenze war fast das Minimum der Stichprobe und hörte auf,
breiter zu werden, wenn das Niveau strenger wurde. Betroffen war genau ein
Urteil, und es war das stärkste: E3.3 lautete „zuverlässig schlechter" bei
[−0,1123; −0,0060] und lautet jetzt **[−0,1091; −0,0001]** — am Rand.
Über sieben Saatwerte war es bei 3 000 Ziehungen 6 zu 1.

**Die Fehlerrichtung war glücklich:** zu wenige Ziehungen machen Intervalle zu
*schmal*, also Effekte zu leicht gesichert — und gesichert wurde hier fast
nichts. *(`audit/BOOTSTRAP_RAND.md`)*

## 10.5 Die Zahl, die alles zusammenfasst

Aus dem bestehenden `study_target_20x.py`, 413 Trades:

| hypothetischer Vorteil je Trade | Endkapital |
|---|---|
| +0,10 R | 1 511 CHF |
| +0,40 R | 5 200 CHF |
| **+0,7280 R** | **20 000 CHF** ← das Ziel |

**Das Ziel verlangt +0,7280 R je Trade über 413 Trades.** Gemessen: −0,0906.
Selbst ein Vorteil von +0,40 R — fünf- bis zehnmal mehr, als gute Systeme
ausweisen — erreicht ein Viertel.

## 10.6 Und ein Termin, der aus einer Rechnung folgt

| nötiger Vorteil | Vorwärtstrades | Tage | fertig am |
|---|---|---|---|
| **+0,7280 R** | **41** | **22** | **30.10.2026** |
| +0,4000 R | 136 | 72 | 19.12.2026 |
| +0,1000 R | 2 175 | 1 145 | 26.11.2029 |

**Der Vorteil, den das Ziel verlangt, wäre bis zum Zieldatum nachweisbar** —
41 Trades bei 1,9 am Tag. Das Ziel prüft sich selbst.

Zeigt der Vorwärtslauf bis dahin kein Intervall ohne Null auf der richtigen
Seite, ist das Ziel **empirisch widerlegt**, nicht nur arithmetisch
unwahrscheinlich. Und die Kehrseite: ein echter Edge von +0,10 R bräuchte
2 175 Trades und bis 2029 — der Vorwärtslauf kann nur **grosse** Vorteile
beantworten. *(`audit/WANN_WEISS_MAN_ES.md`)*

## 10.7 Betrieb

| | |
|---|---|
| **P44 behoben** | Ein Prozess je Rolle, vom Betriebssystem erzwungen (`msvcrt`/`flock`). Ende zu Ende geprüft |
| **Fehlerquoten-Melder** | Ein Ausbruch von ~47 % über zweieinhalb Stunden war unbemerkt geblieben; jetzt meldet er sich |
| **Veraltungs-Wache** | Ein Signalbalken *vor* dem zuletzt entschiedenen wird verworfen; mit `!=` hätte er den Zeiger rückwärts gesetzt |
| **Und ein selbstverschuldeter Ausfall** | Der Melder selbst stürzte den Papierhandel am 09.10. um 13:37 ab — `stats.tally` statt `tally`, sechs Tests grün, Vorrichtung falsch geformt. Acht Minuten, nichts verloren |

**Stand:** 18 Vorwärtstrades, +0,3938 R je Trade, Intervall über die Null,
Konto 12 085,55 USDT. Ratchet: **24 erledigt, 0 offen, 1 nicht testbar.**

---

## Anhang — Reproduktion

```bash
python scripts/ratchet.py                  # 21 erledigt, 0 offen, 1 nicht testbar
python scripts/study_beta_alpha.py         # E8, Beta und Rest
python scripts/study_fill_realism.py       # E9, Falschfüllung
python scripts/study_exits.py              # E3, Ausgänge
python scripts/study_basis.py              # E6, Carry nach Kosten
python scripts/study_target_20x.py         # Ziel-Verteilung
python scripts/papertrade.py               # der laufende Vorwärtshandel
```

Berichte: `audit/E8_ALPHA_ODER_BETA.md`, `audit/E9_FUELL_REALISMUS.md`,
`audit/E3_AUSGAENGE.md`, `audit/CARRY_NACH_KOSTEN.md`,
`audit/TAPE_VOLLE_ABDECKUNG.md`, `audit/TAPE_MAKER_BEFUND.md`,
`audit/FREQAI_VERGLEICH.md`, `docs/TRADING_BRAIN_ZUSTANDSBERICHT.md`.
Vorab-Registrierung aller 49 Vergleiche: `audit/EXPERIMENTS_NEXT.yaml`.
