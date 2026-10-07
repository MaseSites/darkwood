# E0, erster Schritt: die Maut ist nicht mehr der bindende Grund

**Stand:** 07.10.2026 · **Reproduktion:** `python scripts/study_venue_cost.py --samples 5 --pause 15`
**Rohdaten:** `data/quarantine/venue_cost/` (gecachte API-Antworten, damit das Urteil nachprüfbar bleibt)

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
Aufnahme von Quotes und Trades auf BTC und ETH über beide Venues parallel.
Ohne sie ist Punkt 3 oben nicht beantwortbar, und ohne Punkt 3 ist die
Kostenmessung oben interessant und nicht entscheidend.
