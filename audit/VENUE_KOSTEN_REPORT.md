# E0, erster Schritt: die Maut ist nicht mehr der bindende Grund

**Stand:** 07.10.2026 · **Reproduktion:** `python scripts/study_venue_cost.py --samples 5 --pause 15`
**Rohdaten:** `data/quarantine/venue_cost/` — die gecachten API-Antworten, damit ein
erneuter Lauf auf *dieser* Maschine dieselben Zahlen ergibt (`--offline`).
`/data/` ist gitignoriert, also liegt der Cache **nicht** im Repository: wer das
Projekt klont, kann die Zahlen unten nur neu abrufen, nicht nachrechnen. Und
ein neuer Abruf trifft ein anderes Buch. Das ist die Grenze dieser Messung,
nicht ihre Reproduktion.

Dies ist der **erste Schritt** von E0, nicht E0. Was hier gemessen ist: was eine
Ausführung auf einer Null-Gebühren-Venue kostet. Was hier **nicht** gemessen
ist: ob das Signal dieses Projekts dort trägt.

Nur lesend. Keine Authentifizierung, kein Wallet, kein Kapitaltransfer, keine
Order — und das ist nicht eine Absicht, sondern die Bauart des Skripts: es gibt
keinen Codepfad, der etwas sendet.

---

## 1. Warum das überhaupt gemessen wurde

Der Zustandsbericht schloss:

> *„Jeder Vorschlag, der nur die Kosten senkt, kann das Vorzeichen nicht drehen."*

Das war eine Aussage über **alle** Börsen, gezogen aus einer Messung auf
**einer**. `audit/RECHERCHE_KORREKTUREN.md` §3.3 hat sie an zwei Primärquellen
widerlegt. Dieser Bericht misst, was daraus folgt.

---

## 2. Die Gebühren, aus den Marktdaten der Börse selbst

Nicht aus einer Dokumentationsseite, sondern aus dem, was die Börse zu jedem
Markt mitliefert (`/api/v1/orderBooks`, 246 aktive Märkte):

| Markt | maker | taker |
|---|---:|---:|
| BTC, ETH, SOL, XRP, DOGE, LINK | **0,0000 %** | **0,0000 %** |

Das ist der Unterschied zwischen `documented` und `verified_here`: diese Zahlen
stehen in den Instrumentdaten, nicht in einer Marketingseite.

---

## 3. Was eine Ausführung wirklich kostet

Der oberste Spread ist die Zahl, die man zeigt, wenn man eine Börse verkaufen
will. Die Zahl, die ein Trade zahlt, ist der **mittlere Füllpreis gegen die
Buchmitte** — also ein Walk durchs Buch für eine konkrete Ordergrösse.

Fünf Stichproben je Markt, Median:

| Markt | Spread | Tiefe (ask) | 100 USD | 1 000 USD | 5 000 USD | **Runde 1 000 USD** |
|---|---:|---:|---:|---:|---:|---:|
| **BTC** | 0,0002 % | 12 744 995 $ | 0,0001 % | 0,0002 % | 0,0002 % | **0,0005 %** |
| ETH | 0,0042 % | 13 851 571 $ | 0,0025 % | 0,0027 % | 0,0034 % | **0,0054 %** |
| SOL | 0,0059 % | 14 893 219 $ | 0,0030 % | 0,0030 % | 0,0044 % | **0,0059 %** |
| XRP | 0,0146 % | 10 956 077 $ | 0,0073 % | 0,0073 % | 0,0076 % | **0,0146 %** |
| LINK | 0,0339 % | 1 806 735 $ | 0,0169 % | 0,0169 % | 0,0179 % | **0,0339 %** |
| DOGE | 0,0379 % | 1 699 089 $ | 0,0190 % | 0,0190 % | 0,0232 % | **0,0379 %** |

„Runde" ist Taker rein, Taker raus — also zweimal der Walk. Maker-Fills wären
günstiger und sind hier bewusst nicht unterstellt: Maker-Status ist eine
Eigenschaft des Fills, kein Wunsch des Strategen.

---

## 4. Der Vergleich, der die zentrale Aussage dieses Projekts verschiebt

| Grösse | Wert |
|---|---:|
| Maut maker/maker, bisherige Venue (**Boden**) | 0,0400 % |
| Maut maker/taker, bisherige Venue (real) | 0,0750 % |
| Maut des gemessenen Spot-Laufs | 0,1998 % |
| **Obergrenze des gemessenen Einstiegsvorsprungs** | **0,0106 %** |

| Markt | Taker/Taker-Runde, 1 000 USD | gegen den Vorsprung |
|---|---:|---|
| **BTC** | **0,0005 %** | **0,05× — 22 mal darunter** |
| ETH | 0,0054 % | 0,51× — darunter |
| SOL | 0,0059 % | 0,56× — darunter |
| XRP | 0,0146 % | 1,38× — darüber |
| LINK | 0,0339 % | 3,20× — darüber |
| DOGE | 0,0379 % | 3,58× — darüber |

**Auf der bisherigen Börse lag der Boden 3,8-fach über dem Vorsprung. Hier
liegt die ganze Runde auf BTC 22-fach darunter.** Das ist die erste Messung in
diesem Projekt, in der die Gesamtkosten einer Venue unter dem gemessenen
Einstiegsvorsprung liegen.

---

## 5. Was daraus folgt — und was ausdrücklich nicht

**Was folgt:** Die Maut ist nicht mehr der Grund, warum es nicht gehen kann.
Die bisherige Kernaussage — „es ist weniger Vorsprung da als die billigste
denkbare Gebühr" — gilt für Bybit-artige Venues und nicht allgemein.

**Was nicht folgt:** dass es geht. Und die Unterscheidung ist der ganze Punkt.

Der Vorsprung von 0,0070 % [0,0035; 0,0106] wurde auf **5-Minuten-Kerzen einer
anderen Börse** gemessen, mit einer Strategie, die dieses Projekt nicht
geschrieben hat. Ein dort gemessenes Signal wird nicht dadurch zu einem hier
belegten, dass die Ausführung billiger ist. Das ist der Rest von E0 und steht
aus:

1. Dieselben Daten **parallel** auf beiden Venues erfassen, mit lokaler
   Empfangszeit.
2. Den Snapshot **separat** aus den Daten der neuen Venue bauen.
3. Signale der bisherigen Venue mit zeitlich korrekt empfangener Ausführung auf
   der neuen testen — **keine** synthetische Übernahme von Fills.
4. Nicht-Fills, Teil-Fills, verfallene Signale und Cancel-Verzögerung erfassen.
5. Adverse Selektion über Markouts nach 1 s, 5 s, 30 s und 5 min diagnostizieren.
6. Netto-PnL **pro Signal** berichten, nicht pro ausgeführtem Gewinner.

---

## 6. Vorbehalte, die jede Zahl oben trägt

**Fünf Momentaufnahmen sind keine Verteilung.** Spreads weiten sich im Stress —
also genau dann, wenn Signale feuern. Die Tabelle zeigt ein ruhiges Buch an
einem Tag.

**Latenz ist nicht gemessen.** Die Venue dokumentiert für das Standardkonto
300 ms Taker-Verzögerung und 300 ms für Cancel/Modify. Diese Messung liest ein
Buch, das 300 ms später anders aussieht. „0 ms dokumentierte
Zusatzverzögerung" für Maker-Orders bedeutet keine netzwerkfreie Ausführung.

**Tiefe ist nicht Liquidität zu jeder Zeit.** 12 bis 15 Mio. USD auf der
Ask-Seite bei BTC/ETH/SOL sind komfortabel für 1 000 USD. Bei LINK und DOGE sind
es 1,7 bis 1,8 Mio., und dort liegt die Runde ohnehin über dem Vorsprung.

**Die Reihenfolge der Märkte ist nicht die Reihenfolge der Liquidität des
Projekts.** Dieses System handelt zwölf Märkte; drei davon (ATOM, AVAX, DOT)
wurden hier nicht gefunden und sind nicht geprüft.

**Berechtigung und Identität sind ungeklärt.** Ob der Kontoinhaber dort handeln
darf, ist in diesem Projekt offen, und eine Preismessung klärt das nicht. Der
Forschungsauftrag hält ausdrücklich fest, dass die Angaben zum Alter
widersprüchlich sind und bis zur Verifikation nichts daraus abgeleitet wird.

**Und was eine Null-Gebühr nicht ist:** Spread, adverse Selektion, Nicht-Fills,
Funding, Transferkosten und Protokollrisiko bleiben. Null Gebühr heisst null
Gebühr, nicht null Kosten — die Tabelle oben misst genau diesen Unterschied,
und auf LINK und DOGE ist er grösser als die ganze Maut der alten Börse.

## 6b. E0, zweiter Schritt: Nicht-Fills, Stornos und die Warteschlange

Reproduktion: `./.venv/Scripts/python.exe scripts/study_venue_fills.py`

Abschnitt 6 nennt Nicht-Fills unter den Dingen, die eine Null-Gebühr nicht
abschafft. Sie sind jetzt gemessen — **ohne eine einzige Order**, weil das
Buch dieser Venue nicht aggregiert ist: jede Zeile ist eine *einzelne* Order
mit `order_id`, `order_index`, `initial_base_amount` und
`remaining_base_amount`. Dieselbe Order lässt sich über mehrere Aufnahmen
verfolgen, und damit wird beobachtbar, wofür man sonst selbst handeln müsste.

Datengrundlage: dieselben fünf Aufnahmen je Markt wie in Abschnitt 3, im
Abstand von **17,3 s**, Gesamtspanne rund 69 Sekunden. Uhr ist die **lokale
Empfangszeit** der Datei — die Antworten tragen `transaction_time: 0`, und der
Forschungsauftrag verlangt ohnehin lokale Empfangszeiten.

### Die Zahl, auf die es ankommt

| Markt | nachverfolgt | unverändert | **storniert** | weg, Preis durch | verkleinert |
|---|---|---|---|---|---|
| BTC | 1 600 | 49,81 % | **42,44 %** | 7,06 % | 0,69 % |
| ETH | 1 600 | 39,44 % | **49,19 %** | 10,88 % | 0,50 % |
| SOL | 1 600 | 73,25 % | **22,56 %** | 3,62 % | 0,56 % |
| XRP | 1 207 | 77,63 % | **17,73 %** | 3,65 % | 0,99 % |
| LINK | 948 | 87,97 % | **9,49 %** | 2,43 % | 0,11 % |
| DOGE | 815 | 77,79 % | **18,16 %** | 4,05 % | 0,00 % |

„Storniert" heisst: die Order ist verschwunden, **und der Preis hat sie nie
erreicht**. Bei ETH ist nach 17 Sekunden fast die Hälfte der ruhenden Orders
weg, ohne gehandelt worden zu sein.

**Was das für einen Backtest bedeutet.** Ein Simulator, der eine Maker-Order am
Antrittspreis als gefüllt verbucht, nimmt an, dass das Buch dort stehen bleibt.
Es bleibt nicht. Das ist kein Argument gegen die Venue — es ist ein Argument
gegen die Maker-Annahme, auf jeder Venue, und es ist hier zum ersten Mal in
diesem Projekt mit Zahlen hinterlegt.

### Die Warteschlange am Antritt

Bezogen auf **1 000 USD**, die Grösse, mit der dieses Projekt handeln würde:

| Markt | Volumen am Antritt (ask) | 1 000 USD davon | (bid) | davon |
|---|---|---|---|---|
| ETH | 16 996 $ | 5,9 % | 7 708 $ | 13,0 % |
| LINK | 4 610 $ | 21,7 % | 4 551 $ | 22,0 % |
| BTC | 3 036 $ | 32,9 % | **17 $** | **5 969 %** |
| SOL | 2 419 $ | 41,3 % | 8 559 $ | 11,7 % |
| **DOGE** | **1 000 $** | **100,0 %** | 1 296 $ | 77,2 % |
| **XRP** | **499 $** | **200,3 %** | 650 $ | **153,8 %** |

Über 100 % heisst: der Auftrag ist **grösser als das ganze Antrittsniveau** und
kann dort gar nicht vollständig als Maker liegen. Auf XRP ist er doppelt so
gross wie alles, was am besten Preis steht. Unter 100 % passt er hin, steht
aber hinter dem Volumen, das schon da liegt — `order_index` ordnet die
Schlange, und gefüllt wird von vorn.

Und die Bid-Spalte sagt etwas, das die Tiefenzahlen aus Abschnitt 3 nicht
zeigen: **BTCs bester Bid trug in dieser Aufnahme 17 USD.** Die 12,7 Mio. USD
Buchtiefe und 17 USD am besten Preis sind beide wahr. Ein Kauflimit am Antritt
hätte dort alles vor sich gehabt, was in der nächsten Sekunde dazukommt — der
Unterschied zwischen *Tiefe* und *Tiefe dort, wo man handeln will*.

**Das bestätigt die Entscheidung aus Abschnitt 3**, Taker/Taker zu rechnen,
statt sie zu untergraben. Die 0 % Maker-Gebühr ist real; die Maker-*Ausführung*
ist es bei dieser Grösse auf den dünnen Märkten nicht, und auf allen Märkten
macht der Storno-Anteil sie unsicher.

### Was dieses Buch nicht hergibt — und zwei korrigierte Behauptungen

Beide Fehler stammen aus der ersten Fassung dieses Skripts und stehen hier,
weil sie beide plausibel aussahen.

**„Markout" war das falsche Wort.** Ein Markout misst, wie sich der Preis
bewegt, *nachdem man gefüllt wurde* — er bedingt auf den Fill, und genau daraus
entsteht die Aussage über adverse Selektion. Berechnet war die *unbedingte*
Mid-Bewegung: sie sagt, wie weit der Markt gelaufen ist, und sonst nichts. Sie
läuft hier zwischen **−0,605 bp (SOL) und +1,940 bp (LINK)** je 17 s. Ein
Maker-Markout in dieser Grössenordnung wäre derselbe Marktlauf noch einmal.

**Eine schrumpfende `remaining_base_amount` ist kein Beleg für eine
Ausführung.** Sie war als „harter Beleg" bezeichnet. Ein einziger Fall hat das
widerlegt: auf LINK schrumpfte eine Order **394 bp vom Mid entfernt**. Ein Ask
4 % über dem Markt wird in 17 Sekunden nicht gehandelt — der Eigentümer hat die
Grösse reduziert.

Über alle Märkte: **von 41 Verkleinerungen liegen 33 an Preisen, die der Markt
im Fenster nie erreicht hat.** Die können keine Ausführung gewesen sein. Die
verbleibenden 8 sind *Kandidaten* — die Erreichbarkeitsprüfung („der beste Ask
muss im Fenster mindestens bis zu diesem Preis gestiegen sein") ist eine
**notwendige** Bedingung aus den Daten, keine erfundene Schwelle, und notwendig
ist nicht hinreichend.

**Daraus folgt für das Datenmanifest:** *ohne Trade-Tape kann dieses Buch keinen
Fill belegen.* Ein Markout auf 8 Kandidaten gegen eine unbedingte Drift
derselben Grössenordnung ist keine Aussage über adverse Selektion, und es wird
hier keine getroffen.

### Grenzen dieses Laufs, ohne Beschönigung

Fünf Aufnahmen je Markt, ein Vormittag, 69 Sekunden Gesamtspanne, kein Stress,
keine Tageszeiten, kein Trade-Tape. **Belegt ist die Messung** — dass
Storno-Anteil, Warteschlange und Teil-Verkleinerungen aus diesem Orderbuch ohne
eigene Order ablesbar sind. Die Zahlen sind eine erste Lesung und keine
Charakterisierung dieser Venue.

Die Horizonte, die der Auftrag nennt, sind damit teilweise offen: **1 s und 5 s**
brauchen einen Streaming-Collector, **5 min** eine längere Aufnahme. Die
Cancel-*Verzögerung* (dokumentiert: 300 ms) ist nicht gemessen, sondern nur der
Cancel-*Anteil*. Und die **drei fehlenden Märkte** (ATOM, AVAX, DOT) sind auch
hier nicht geprüft.

---

## 7. Entscheidung

**E0 bleibt offen und wird zur ersten Priorität.** Die Freigabebedingung aus der
Registrierung ist nicht erfüllt und auch nicht verfehlt — sie ist noch nicht
geprüft: *„positiver, korrekt korrigierter Nettoeffekt auf
Entwicklung/Bestätigung; keine bloss aus Gebührenrabatt übernommene Wirkung."*

**Kein Kapital bewegt sich.** Die Venue bleibt Daten- und Shadow-Quelle. Für
mehr bräuchte es einen eigenen Review von Kontoberechtigung, Orderschutz und
tatsächlichen Handelsrechten — und der ist hier nicht vorbereitet, indem
Schutzregeln still ausgeschaltet werden.

**Der nächste konkrete Schritt** ist die kontinuierliche, zeitgestempelte
Aufnahme von Quotes **und Trades** auf BTC und ETH über beide Venues parallel.
Ohne sie ist Punkt 3 oben nicht beantwortbar, und ohne Punkt 3 ist die
Kostenmessung oben interessant und nicht entscheidend.

Abschnitt 6b hat diesen Schritt enger gefasst als er vorher war. Das **Trade**-
Tape ist nicht optional: ohne es lässt sich in diesem Buch eine Teilausführung
nicht von einer Teil-Storno trennen, und damit gibt es keinen Markout. Die
Aufnahme muss also beides führen, nicht nur Quotes — was der Auftrag in E0
Punkt 1 ohnehin verlangt und was hier jetzt mit einem Grund hinterlegt ist
statt nur mit einer Forderung.

Was 6b **schon beantwortet** hat und nicht mehr auf die Sammlung wartet:
Nicht-Fills (als Storno-Anteil), die tatsächlich verfügbare Orderbuchgrösse und
die Warteschlange am Antritt. Offen bleiben aus Auftragspunkt 6: die
Cancel-**Verzögerung** (dokumentiert 300 ms, nicht gemessen), verfallene
Signale, und Teil-Fills als belegte Ereignisse.
