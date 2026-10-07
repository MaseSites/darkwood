# Recherche-Korrekturen — jede Behauptung nachgerechnet

**Stand:** 07.10.2026 · **Grundlage:** `TRADING_BRAIN_CLAUDE_RECHERCHE_UND_UMBAUPROMPT.md`, Abschnitt 3
**Gegenstand:** acht Aussagen, mit denen die externe Recherche meinen Zustandsbericht korrigiert.

Jede wurde hier mit Code oder Handrechnung geprüft, nicht übernommen. Das Ergebnis steht
vor der Begründung, und wo die Recherche recht hat, steht das ohne Abschwächung da.

| # | Behauptung der Recherche | Mein Befund |
|---|---|---|
| 3.1 | Ein negativer Pool schliesst profitable Teilmengen nicht aus | **bestätigt, an meinen eigenen Daten** |
| 3.2 | Der Stop-Abstand kürzt sich nicht allgemein heraus | **bestätigt, und schärfer als behauptet** |
| 3.3 | 0,04 % ist keine physikalische Gebührenuntergrenze | **bestätigt an zwei Primärquellen** |
| 3.4 | Die alte Zielrechnung mischt Risikoannahmen | **bestätigt** |
| 3.5 | Die 61,8 % sind nicht reproduzierbar | **bestätigt — und schlimmer: sie sind falsch** |
| 3.6 | Baselines müssen zur Frage passen | bestätigt, grösstenteils schon eingehalten |
| 3.7 | Null-Funding ist ein Anomaliesignal, kein Korruptionsbeweis | **bestätigt — mein Ausschluss von BNBUSDT war falsch** |
| 3.8 | Funding-Trend über elf korrelierte Märkte ist kein elffacher Beweis | **bestätigt; der Trend selbst überlebt die korrekte Prüfung** |

**Und ein Befund, den die Recherche nicht kennen konnte, weil ihr der Code fehlte:**
Die Funding-Daten **mischen zwei Börsen** (Abschnitt 3.7b). Das ist der schwerere Defekt.

---

## 3.1 Ein negativer Pool schliesst profitable Teilmengen nicht aus

**Was ich geschrieben hatte** (Zustandsbericht 6.4): *„Solange die regelbasierte Auswahl
keinen Vorteil hat, kann eine Auswahl unter diesen Einträgen nichts beitragen — man kann aus
nichts keine bessere Teilmenge ziehen."*

**Das ist falsch**, und zwar nicht nur theoretisch. Nachgerechnet über die 2 734
Replay-Trades des Journals:

```
GESAMTPOOL                n=2734   -0.0906 R

Nach Markt:
  BTCUSDT                 n= 495   +0.0266 R   <-- POSITIV
  SOLUSDT                 n= 857   -0.0926 R
  ETHUSDT                 n= 638   -0.1103 R
  XRPUSDT                 n= 744   -0.1495 R

Nach rating_band (vor dem Trade berechnet):
  eindeutig               n= 588   +0.0311 R   <-- POSITIV
  Durcheinander           n= 279   -0.0626 R
  gemischt                n= 786   -0.1126 R
  deutlich                n= 691   -0.1477 R
  unklar                  n= 390   -0.1491 R

Nach Setup:   A -0.0420 | B -0.0795 | G -0.1206 | C -0.1494
Nach Seite:   short -0.0502 | long -0.1521
```

Beide positiven Teilmengen sind über **ex ante bekannte** Merkmale definiert: der Markt steht
fest, und `rating_band` wird von der Bewertungsschicht vor dem Einstieg erzeugt.

**Mein Fehler war ein Kategoriefehler:** Ich habe „der Mittelwert des Pools ist nicht von null
zu trennen" mit „keine Teilmenge hat einen positiven Mittelwert" gleichgesetzt. Das zweite
folgt nicht aus dem ersten. Besonders peinlich, weil dieses Projekt **bereits danach
gehandelt** hat: Setup C wurde am 04.10.2026 genau deshalb abgeschaltet, weil seine Teilmenge
schlechter war als der Rest. Die Aussage in 6.4 widerspricht einer Entscheidung, die drei
Tage vorher auf derselben Grundlage getroffen wurde.

**Was dennoch gilt, und es ist der eigentliche Punkt:** Die positive Teilmenge muss sich
**auf neuen Daten** wiederfinden lassen. Darum zusätzlich das Intervall und die Kontrolle,
die der Auftrag verlangt (Wochenblock-Bootstrap, 10 000 Ziehungen):

```
GESAMTPOOL              n=2734   -0.0906 R   [-0.1513, -0.0308]
rating_band=eindeutig   n= 588   +0.0311 R   [-0.0934, +0.1607]

Zufallsfilter gleicher Selektivitaet (21.5%):
  Mittel -0.0902 R, 95%-Spanne [-0.1886, +0.0141]
```

Also: **absolut ist es kein Fund** — das Intervall umspannt die Null. Gegen einen
Zufallsfilter derselben Selektivität liegt +0,0311 R knapp über dessen 97,5-%-Punkt
(+0,0141). Das ist ein **Kandidat für E1**, kein Ergebnis.

**Konsequenz:** Der Satz in 6.4 wird ersetzt. Meta-Labeling (E1) ist damit nicht nur erlaubt,
sondern die am besten begründete offene Frage im Projekt.

Reproduktion: `python scripts/study_subset.py`

---

## 3.2 Der Stop-Abstand kürzt sich nicht allgemein heraus

**Was ich geschrieben hatte:** `net_r = (eingefangene Bewegung − Gebühr) / Stop-Abstand`,
daher *„Stop, Positionsgrösse und Hebel kürzen sich heraus"* — und daraus: jeder Vorschlag
mit engeren oder weiteren Stops sei arithmetisch erledigt.

**Die Positionsgrösse kürzt sich heraus. Der Stop nicht.** Er steht im Nenner, und — das ist
der Punkt, den ich übersehen habe — **er verändert den Pfad**, weil er den Ausstiegszeitpunkt
verschiebt. Nachgerechnet über die 1 858 ausgestoppten Replay-Trades, aus den
Post-Mortem-Feldern, die das Journal ohnehin speichert:

```
max_adverse_r der ausgestoppten Trades:
  Median 1.265, Quantile 25/75/90: 1.089 / 1.616 / 2.334
  94.2% waren vorher im Plus, 52.8% davon ueber +0.5 R

Ein weiterer Stop haette diese Trades nicht beendet:
  Stop 1.25x so weit ->  47.8% waeren NICHT ausgestoppt worden
  Stop 1.50x so weit ->  70.1% waeren NICHT ausgestoppt worden
  Stop 2.00x so weit ->  85.8% waeren NICHT ausgestoppt worden
  Stop 3.00x so weit ->  94.3% waeren NICHT ausgestoppt worden
```

Bei einem Stop 1,5× so weit hätten **70,1 %** der heute ausgestoppten Trades einen anderen
Ausgang, eine andere Haltezeit, ein anderes Funding und eine andere Gebührenbilanz. Die
Annahme „gleicher Pfad" ist für die Mehrheit der Trades verletzt.

**Die korrekte Formulierung**, die ins Projekt übernommen wird:

> Bei **festem Pfad** ändert ein anderer Stop nur den Nenner, nicht das Vorzeichen des
> Zählers. Sobald der Stop den Ausstieg verschiebt, ist der Pfad nicht mehr fest, und die
> Aussage gilt nicht. „Engerer Stop, gleiche Bewegung angenommen" bleibt widerlegt;
> „anderer Stop, Pfad neu simuliert" ist eine zulässige Studie.

**Konsequenz:** E3 (Ausgänge als Handelspolitik) ist eine legitime Untersuchung.
Das Gedächtnis-Dokument `stop-width-cannot-flip-the-sign` wird entsprechend eingeschränkt.

Reproduktion: `python scripts/study_stop_path.py`

---

## 3.3 0,04 % ist keine physikalische Gebührenuntergrenze

**Was ich geschrieben hatte:** 0,0400 % sei *„der Boden dieser Börsenfamilie"* — korrekt
formuliert und auf Bybit-artige Venues bezogen. Aber ich habe daraus die unzulässige
Verallgemeinerung gezogen: *„Jeder Vorschlag, der nur die Kosten senkt, kann das Vorzeichen
nicht drehen."*

**An den Primärquellen abgerufen am 07.10.2026** (nicht aus der Recherche übernommen):

| Venue / Profil | Maker | Taker | Maker/Maker | Quelle |
|---|---:|---:|---:|---|
| Bybit, Basisstruktur (Projektannahme) | 0,0200 % | 0,0550 % | 0,0400 % | Projekt-Spec |
| **Lighter Standard** | **0 %** | **0 %** | **0 %** | apidocs.lighter.xyz/docs/account-types |
| Lighter Plus | kombiniert 0,005 % | — | — | ebd. |
| Lighter Premium, 0 LIT gestakt | 0,0040 % | 0,0280 % | **0,0080 %** | ebd. |
| Lighter Premium, 500 000 LIT | 0,0028 % | 0,0196 % | 0,0056 % | ebd. |
| **Extended, Orderbuchmärkte** | **0,000 %** | **0,025 %** | **0 %** | docs.extended.exchange |
| Extended, RWA-Märkte | 0,000 % | 0,010 % | 0 % | ebd. |

Damit ist die Verallgemeinerung widerlegt. **Lighter Premium Maker/Maker mit 0,0080 % liegt
unter der Obergrenze meines gemessenen Einstiegsvorsprungs (0,0106 %)**, und Lighter Standard
berechnet gar keine Gebühr.

**Was ich bei der Prüfung zusätzlich gefunden habe und was die Sache dämpft:**

1. **Lighter Standard erkauft 0 % mit Latenz:** 300 ms Taker-Verzögerung, 300 ms
   Cancel/Modify, 0 ms Maker, TWAP 1 bp. Premium senkt Taker-Latenz auf 140 ms. „0 ms
   dokumentierte Zusatzverzögerung" ist keine netzwerkfreie Ausführung.
2. **Extendeds Maker-Rebates sind für dieses Konto unerreichbar:** Sie verlangen ≥ 0,5 %
   Marktanteil über 30 Tage und mindestens 10 USD Anfall in 24 Stunden. Mit 1 000 CHF
   Kapital spielt das keine Rolle. Die 0,000 % Maker gelten aber ohne Bedingung.
3. **Gebühr ist nicht Kosten.** Spread, adverse Selektion, Nicht-Fills, Funding und
   Transferkosten bleiben. Ein auf Binance gemessenes Signal wird nicht dadurch zu einem auf
   Lighter belegten Signal, dass man eine Gebührenzahl austauscht.

**Konsequenz, und sie ist die wichtigste dieses Berichts:** Die Frage „lohnt es, die Maut zu
jagen?" war mit „nein" beantwortet. Diese Antwort gilt nur für die eine Börsenfamilie, auf
der gemessen wurde. **E0 wird damit die erste Priorität**, und die Begründung ist Arithmetik:
Bei 0 % Gebühr entscheidet nicht mehr die Maut über das Vorzeichen, sondern Spread, Latenz
und adverse Selektion — drei Grössen, die dieses Projekt **nie gemessen** hat.

Der Satz im Zustandsbericht und in `scripts/study_freqtrade_gross.py` wird entsprechend
eingeschränkt: Die 0,0400 % sind der Boden **dieser** Venue, nicht des Marktes.

---

## 3.4 Die alte Zielrechnung mischt Risikoannahmen

**Bestätigt.** `scripts/goal.py:140` rechnet:

```python
risk_chf = initial_equity * uncalibrated_cap_risk_pct      # 1000 * 0.01 = 10.00 CHF, FEST
risk_fraction = risk_chf / equity                          # 10 / 12004 = 0.0833%
needed = (growth ** (1.0 / trades) - 1.0) / risk_fraction  # geometrisch, feste FRAKTION
```

Die Formel modelliert geometrisches Wachstum bei **konstanter Fraktion**. Das System
riskiert aber einen **konstanten CHF-Betrag** (1 % eines festen 1 000-CHF-Kontos). Beide
stimmen nur für kleine Wachstumsfaktoren überein.

Die Gegenrechnung der Recherche ist korrekt und reproduziert:
55 Chancen × 2,15 R × 10 CHF = **1 182,50 CHF**, gegen eine Lücke von 2 995,72 CHF. Auch
perfektes Spiel bei festem CHF-Risiko reicht nicht — was mit dem Faktor 2,3 aus `goal.py`
konsistent ist (4,92 / 2,15 = 2,29).

**Zusätzlich korrigiere ich meine eigene Wortwahl:** Ich habe das mittlere geplante
Chance-Risiko-Verhältnis als *„MAXIMUM"* und *„das physikalisch Möglichste"* bezeichnet. Es
ist die **Obergrenze unter dem festgelegten Auszahlungsschema** — also unter der Annahme,
dass jeder Trade sein vorab gesetztes Ziel trifft. Ein anderes Exit-Schema hat eine andere
Obergrenze. Das ist genau die Lücke, die 3.2 öffnet.

**Konsequenz:** Die Zielrechnung wird auf **ein** Konto und **eine** Kapitalbasis
umgestellt (Abschnitt 10.2 des Auftrags), und Kapitalbasis, Reinvestition und Formel
verwenden dieselben Annahmen. Das neue Ziel (1 000 → 20 000 in 182 Tagen) macht die alte
Rechnung ohnehin gegenstandslos; der Defekt wird trotzdem behoben, weil dieselbe Funktion die
neue Rechnung trägt.

---

## 3.5 Die 61,8 % sind nicht reproduzierbar — sie sind falsch

**Die Recherche sagt:** *„Die im Bericht genannten 61,8 % sind ohne andere explizite Annahmen
nicht aus diesem Modell reproduzierbar."*

**Bestätigt, und es ist schlimmer als „nicht reproduzierbar".** Nachgerechnet mit der
Projektfunktion `learn/target.py::required_hit_rate` und unabhängig per Hand:

```
G=20, n=312, Risiko 3%
  Payout(win=1.5612, loss=1.0384)  -- die in ZIELRECHNUNG.md genannte  ->  53.28%
  Payout(win=1.816,  loss=1.008)   -- die im Zustandsbericht genannte  ->  48.13%
  Payout(win=1.0,    loss=1.0)     -- symmetrisch                      ->  66.75%
```

Die Zahl **61,8 % erscheint bei keiner dieser Auszahlungen**. Und `audit/ZIELRECHNUNG.md`
behauptet ausdrücklich, sie stamme aus `Payout(win=1.5612, loss=1.0384)` bei 3 % und 312
Trades — dort stehen **53,28 %**.

**`git log --follow` zeigt, dass `target.py` seit dem Commit, der ZIELRECHNUNG.md einführte
(`ef30e93`), unverändert ist.** Die 61,8 % wurden also nie von diesem Code erzeugt. Sie sind
handgeschrieben.

Das ist der bitterste Einzelbefund dieses Berichts: Das Dokument, dessen erklärter Zweck
*„meine eigenen Zahlen geprüft"* war, enthält selbst eine handgeschriebene Zahl, die sein
eigener Code widerlegt — genau der Fehler, den es bei der 56,6 % aufgedeckt hat. Die Lehre
„eine Zahl, die zitiert wird, muss in einem Skript stehen" wurde im selben Dokument
formuliert und im selben Dokument verletzt.

**Zusätzlich bestätigt:** Die komplette Tabelle aus Abschnitt 4 des Auftrags ist mit
`target.py` **und** mit unabhängiger Handrechnung exakt reproduzierbar:

| Trades | 1 % | 2 % | 3 % |
|---:|---:|---:|---:|
| 60 | 213,52 % | 125,43 % | 96,28 % |
| 156 | 104,29 % | 70,61 % | 59,59 % |
| 312 | 70,15 % | 53,47 % | 48,13 % |
| 624 | 53,08 % | 44,91 % | 42,39 % |

(Werte über 100 % heissen: im Modell unerreichbar.)

**Konsequenz:** `audit/ZIELRECHNUNG.md` wird korrigiert, und jede Prozentzahl im Projekt wird
an eine Funktion gebunden statt an einen Satz. Siehe `tests/test_target.py` für die
Regressionsprüfung, die das künftig fängt.

Reproduktion: `python scripts/study_hitrate_table.py`

---

## 3.6 Baselines müssen zur Frage passen

**Bestätigt.** Die Liste des Auftrags deckt sich mit den Regeln, die das Projekt schon führt
(Zustandsbericht 12), mit einer Ergänzung, die ich übernehme:

> **Profitabilität ist eine eigene Frage.** Ein verlierender Benchmark macht einen kleineren
> Verlust nicht zum Gewinn.

Das Register vergleicht Arme gegen den Champion (−0,0340 R). Ein Arm bei −0,015 R „schlägt
den Champion" und verliert trotzdem Geld. `scripts/ratchet.py::decide` sagt das inzwischen
ausdrücklich — *„Besser als Champion bedeutet noch nicht profitabel"* wird als zweite,
getrennte Abnahmebedingung in `audit/EXPERIMENTS_NEXT.yaml` geführt.

---

## 3.7 Null-Funding: mein Ausschluss von BNBUSDT war falsch

**Was ich am 06.10.2026 getat habe:** BNBUSDT aus der Funding-Studie ausgeschlossen, weil
49,6 % der Abrechnungen exakt null sind, mit der Begründung *„Keine Börse rechnet so oft
genau nichts ab — das ist ein Loch in den Daten, kein Markt ohne Funding."*

**Das war eine Plausibilitätsannahme, keine Messung.** Der Auftrag verlangt den Vergleich mit
der offiziellen Historie derselben Venue. Durchgeführt am 07.10.2026:

```
Binance BNBUSDT, letzte 200 Abrechnungen (02.08. - 07.10.2026):
  exakt null: 73 = 36.5%
  Raster: 8h
  gemeinsame Zeitstempel mit meiner Datei: 200, davon beide null: 73
  Uebereinstimmung: 100.0%
```

**Die Nullen sind echt.** Es sind `observed_zero`, nicht `imputed_zero` und nicht `missing`.
Binance rechnet für dieses Symbol in einem Band tatsächlich exakt null ab, und meine Datei
gibt die Börse zu 100,0 % korrekt wieder — Nullen eingeschlossen.

**Konsequenz:** Die Schwelle `MAX_ZERO_SHARE` wird aus `study_funding_carry.py` entfernt und
durch eine Prüfung ersetzt, die gegen die Venue abgleicht statt gegen eine Vermutung. Die
Überschrift „11 von 11" war durch einen falschen Ausschluss entstanden.

Reproduktion: `python scripts/verify_funding_provenance.py`

---

## 3.7b Der Befund, den die Recherche nicht sehen konnte: zwei Börsen in einem Verzeichnis

Bei derselben Prüfung ist etwas Grösseres herausgekommen. Der Abgleich aller zwölf
Funding-Dateien gegen **beide** Venue-APIs:

| Markt | Binance | Bybit | Urteil | Historie beginnt |
|---|---:|---:|---|---|
| BTCUSDT | 28,9 % | **96,2 %** | Bybit | 2023-01-01 |
| ETHUSDT | 28,9 % | **96,2 %** | Bybit | 2023-01-01 |
| SOLUSDT | 37,7 % | **96,2 %** | Bybit | 2023-01-01 |
| XRPUSDT | 43,0 % | **97,3 %** | Bybit | 2023-01-01 |
| ADAUSDT | **100,0 %** | 42,4 % | Binance | 2020-01-19 |
| ATOMUSDT | **100,0 %** | 19,2 % | Binance | 2020-02-06 |
| AVAXUSDT | **100,0 %** | 31,3 % | Binance | 2020-09-22 |
| BNBUSDT | **100,0 %** | 0,0 % | Binance | 2020-02-10 |
| DOGEUSDT | **100,0 %** | 32,3 % | Binance | 2020-07-10 |
| DOTUSDT | **100,0 %** | 47,5 % | Binance | 2020-08-20 |
| LINKUSDT | **100,0 %** | 33,3 % | Binance | 2020-01-17 |
| LTCUSDT | **100,0 %** | 25,3 % | Binance | 2020-01-09 |

**Vier Märkte sind Bybit, acht sind Binance.** Das Muster ist eindeutig: die vier
ursprünglichen Märkte wurden von Bybit geholt, die acht später hinzugefügten von Binance —
daran erkennbar, dass die Bybit-Reihen 2023 beginnen und die Binance-Reihen 2020.

**Das Projekt wusste es und hat es ignoriert.** `learn/panel.py::SOURCES` führt
`funding` seit Tagen als `funding (gemischte Boerse)` und `check_provenance("P+D")` meldet
es als einziges verbleibendes Herkunftsproblem. **Meine Funding-Carry-Studie hat
`check_provenance` nie aufgerufen.** Eine Schutzvorrichtung, die existiert und nicht benutzt
wird, ist keine.

Konsequenzen für die Studie:

1. Zwei Venues haben verschiedene Funding-Formeln, verschiedene Deckel und können
   verschiedene Intervalle haben. Ein Mittelwert über beide ist keine Grösse.
2. **Mein Halb-Halb-Split verglich verschiedene Kalenderfenster je Markt**: Bybit-Märkte
   teilen bei 2024-11-19, Binance-Märkte bei 2023-05/09. „11 von 11 fallend" war damit auf
   ungleichen Fenstern gemessen.

**Auf dem gemeinsamen Fenster neu gerechnet** (2023-01-01 bis 2026-10-07, 4 126 Perioden je
Markt, Hälften also kalendergleich):

```
Markt      Venue       erste      zweite   Verh.
ADAUSDT    Binance   +0.0093%   +0.0035%   0.38x
ATOMUSDT   Binance   +0.0043%   -0.0075%  -1.74x
AVAXUSDT   Binance   +0.0078%   +0.0014%   0.18x
BNBUSDT    Binance   -0.0064%   +0.0008%  -0.12x   <-- steigt
BTCUSDT    Bybit     +0.0092%   +0.0043%   0.46x
DOGEUSDT   Binance   +0.0107%   +0.0042%   0.40x
DOTUSDT    Binance   +0.0055%   -0.0002%  -0.04x
ETHUSDT    Bybit     +0.0090%   +0.0045%   0.50x
LINKUSDT   Binance   +0.0103%   +0.0054%   0.52x
LTCUSDT    Binance   +0.0104%   +0.0049%   0.48x
SOLUSDT    Bybit     +0.0078%   +0.0021%   0.27x
XRPUSDT    Bybit     +0.0115%   +0.0038%   0.33x

Fallend: 11 von 12 (Bybit 4/4, Binance 7/8)
```

**Der Rückgang überlebt die korrekte Prüfung.** Er ist kein Venue- und kein
Fensterartefakt — er zeigt sich auf gemeinsamem Kalenderfenster und in beiden
Venue-Gruppen getrennt.

---

## 3.8 Elf korrelierte Märkte sind kein elffacher Beweis

**Was ich geschrieben hatte:** *„Eine einheitliche Richtung über elf Märkte ist kein
Rauschen. Rauschen streut; das hier fällt überall."*

**Der erste Satz überschätzt, was die Beobachtung trägt.** Die zwölf Märkte bewegen sich
gemeinsam — das ist dieselbe Korrelation, die den gesamten Querschnittsarm begründet
(Zustandsbericht 8.2). Elf gleichgerichtete Beobachtungen eines gemeinsamen Faktors sind
näher an **einer** Beobachtung als an elf.

Die konservative Formulierung, die übernommen wird:

> Der Rückgang ist auf gemeinsamem Kalenderfenster in 11 von 12 Märkten und in beiden
> Venue-Gruppen vorhanden. Weil die Märkte stark korreliert sind, ist das **eine**
> gut belegte Beobachtung eines gemeinsamen Trends, nicht elf unabhängige Bestätigungen.
> Die Ursache ist offen: Crowding des Basis-Trades, Zinsumfeld, Regeländerungen der Venues
> und Regimewechsel sind alle nicht ausgeschlossen. **[VERMUTUNG]** bleibt die
> Crowding-Erklärung.

Zur Survivorship-Richtung: Ich hatte behauptet, der Bias zeige *„in Richtung eines positiven
Ergebnisses"*. Das gilt für einen Long-Arm, der vergangene Gewinner kauft. Für Long/Short,
Shortbarkeit und Delisting-Abrechnung ist die Richtung **nicht** ohne Prüfung festgelegt —
diese Einschränkung übernehme ich und markiere die bisherige Aussage als nur für den
Long-Fall begründet.

---

## Was aus diesen acht Korrekturen folgt

| Vorher blockiert | Jetzt offen |
|---|---|
| „Auswahl kann nichts beitragen" | **E1 Meta-Labeling** — bestbegründete offene Frage |
| „Stops sind arithmetisch erledigt" | **E3 Exit-Politik** — 70 % der Trades hätten anderen Pfad |
| „Keine Gebührensenkung kann helfen" | **E0 Venue-/Kostenvergleich** — erste Priorität, 0 %-Venues dokumentiert |
| „BNBUSDT-Daten sind kaputt" | Nullen sind echt; der Defekt ist die **Venue-Mischung** |

**Was nicht offen wird:** Keine dieser Korrekturen zeigt einen Vorteil. Sie entfernen vier
Begründungen, mit denen ich Untersuchungen vorzeitig geschlossen hatte. Das Register bleibt
bei **kein belegter Vorteil**, und die vier Untersuchungen oben sind Aufträge, keine
Ergebnisse.
