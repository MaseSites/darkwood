# Briefing 03 für ChatGPT — ist diese Strategiefamilie erschöpft?

> **Kopiere dieses Dokument vollständig in ChatGPT.** Es ist selbsttragend; es
> braucht keinen Zugriff auf Code oder Daten.

---

## Was ich von dir will, und was ausdrücklich nicht

Ich will **keine neuen Ideen für Handelsstrategien** und **keine Literatursuche**.
Beides ist in drei unabhängigen Programmen gelaufen und steht unten als Ergebnis.

Ich will ein **Urteil über ein Fazit** — und zwar von jemandem, der es nicht
selbst produziert hat. Claude hat alle Negativbefunde unten selbst gemessen und
kann seine eigene Suche nicht auf blinde Flecken prüfen. Das ist der ganze
Auftrag.

**Die Frage, in einem Satz:** Ist der korrekte Schluss aus den Messungen unten,
dass diese Strategiefamilie erschöpft ist — oder gibt es eine Achse, die nie
*gestellt* wurde?

Und die zweite, die genauso wichtig ist: **Wenn die Antwort „erschöpft" lautet,
sage das.** Ein „ihr könntet noch X probieren", bei dem X höchstens 0.01 R
bewegt, ist keine Hilfe, sondern kostet weitere Wochen. Die ehrliche Antwort
„das Ding hat keine Kante, hört auf" ist ein zulässiges und wertvolles Ergebnis.

---

## 1. Das System und das Ziel

Krypto-Perpetuals, zwölf Märkte (BTC, ETH, SOL, XRP, ADA, AVAX, LINK, DOGE, BNB,
LTC, DOT, ATOM). Ein regelbasiertes System mit sechs Setups auf Preisstruktur
(Momentum-Breakout, Trendlinien-Fakeout, Supply-Demand-Retest,
NOC-Orderblock, Inducement-Orderblock, Six-Factor-Gap). Signalebene M15,
Ausführungsauflösung M1, Kontextebenen W1/D1/H4/H1.

Ein Trade entsteht so: ein Setup feuert → Stop an Struktur → Ziel bei
mindestens 1,5 R → Positionsgrösse = Risikobudget / Stopabstand → Hebel so,
dass die Liquidation mindestens 2,5 Stopweiten hinter dem Stop liegt.

**Das Ziel:** 1.000 → 20.000 (Faktor 20) in etwa sechs Monaten.

**Was das erfordert, korrekt gerechnet:** `+0.42 R je Trade`. Diese Zahl ist
schon einmal falsch gewesen und hier ist die Korrektur, weil sie für dein
Urteil zentral ist: der Durchsatz wurde zuerst mit der **Median**-Haltedauer
gerechnet und ergab 269 Gelegenheiten und +0.081 R. Little's Law braucht die
**mittlere** Haltedauer. Korrigiert: Kapazität 3,64 Trades/Tag statt 17,9, also
**51 Gelegenheiten statt 269**, und der nötige Erwartungswert springt von
+0.081 R auf **+0.42 R**.

---

## 2. Was das System tatsächlich liefert

**Die Hauptmessung:** 7.335 Fills über zwölf Märkte, rund fünf Jahre, ein
gepooltes Konto von 1.000 USDT, Kostenmodell und Füllmodell unten beschrieben.

```
Erwartungswert   -0.0129 R je Trade
95%-Intervall    [-0.0868, +0.0594]   (Bootstrap, 20.000 Ziehungen)
Auflösungsgrenze des Apparats   ±0.0774 R bei 12 Märkten
```

Das Intervall enthält die Null. Das System ist **nicht verlässlich negativ** und
**kein Gewinner**. Die Anforderung (+0.42 R) liegt beim **5-fachen der oberen
Intervallgrenze** und beim **32-fachen des Mittelwerts in absoluten Zahlen**.

**Die Zerlegung, die das Problem benennt:** der durchschnittliche Trade erreicht
unterwegs **+1.1840 R** und endet bei **−0.0129 R**. Und **62,9 % berühren ihr
Ziel nie**. Es ist also kein Problem, Bewegung zu finden — es ist ein Problem,
sie zu behalten. Genau diese Beobachtung hat zu E14/E15 geführt (siehe unten),
und beide sind gefallen.

**Und ein Befund, der die Richtung erklärt:** eine Beta-Zerlegung gegen BTC
ergibt Beta 1,0 mit einem **verlässlich negativen Residuum**. Das System ist
gehebeltes Beta auf Bitcoin und nichts anderes. Die +0.80 R, die eine frühere
Vorwärtsstichprobe zeigte, waren Hebel auf Richtung.

---

## 3. Die vollständige Liste der geschlossenen Achsen

Jede Zeile ist eine abgeschlossene Messung mit Intervall, nicht eine Vermutung.
**Ein Vorschlag, der auf eine dieser Zeilen zurückfällt, ist keine Hilfe.**

### 3.1 Kosten — am 18.10.2026 quantitativ geschlossen

Anlass: der Gebührenplan kam von der falschen Börse. Die Konfiguration steht auf
Binance (taker 0,0500 %), das Spec-Objekt trug Bybits 0,0550 %. Alle 7.335 Fills
sind darunter entstanden. Exakt nachgerechnet je Fill, ohne Neulauf:

| Gebührenplan | Erwartungswert | Gebühr gesamt | Δ gegen Legacy |
|---|---|---|---|
| Legacy wie gespeichert | −0.0129 R | 2.043,87 USDT | — |
| venue-korrekt, gleiche Rollen | −0.0114 R | 1.939,51 | **+0.0014 [+0.001, +0.002]** |
| venue-korrekt, nur Taker (Policy A) | −0.0304 R | 3.283,24 | −0.0170 [−0.018, −0.017] |
| **null Gebühren — die Obergrenze** | **+0.0164 R [−0.016, +0.048]** | 0,00 | +0.0290 [+0.028, +0.029] |

**Die ganze Kostenachse ist +0.029 R wert.** Eine Börse, die *nichts* kostet,
bringt +0.0164 R mit einem Intervall, das die Null enthält — gegen eine
Anforderung von +0.42 R. Faktor **>25**.

Und diese Obergrenze ist **optimistisch**, nicht vorsichtig: bei null Gebühren
kann die Kostenregel (`max_cost_fraction_of_risk = 0,08`) nie mehr auslösen, die
Zahl behält also den Nutzen einer Auswahl, deren Kosten sie auf null setzt — und
die von dieser Regel abgelehnte Population ist gemessen brutto-negativ. Ein
echter Nullgebühren-Lauf wäre **schlechter**.

Zweiter Teil derselben Achse: die echten Instrumentregeln der Börse (Tick,
Schrittweite, Mindestnominal, je Symbol verschieden, teils Faktor 1000 gegen die
Annahme) lehnen **2 von 7.335 Fills** ab, −0.0002 R. Die Venue-Verwechslung
kostete also exakt die Gebührendifferenz und sonst nichts.

Unabhängige Bestätigung: ein Freqtrade-Lauf über 19 Monate und 15.624 Trades
findet die Einstiegskante **3,8× kleiner als einen Maker/Maker-Roundtrip**.

### 3.2 Richtung — gemessen und gescheitert

Erst die Rahmenrechnung: mittlere absolute Bewegung gegen die Gesamtkosten,
175.380 H1-Fenster, 4 Märkte:

| Horizont | mediane Bewegung | Bewegung/Kosten | nötige Treffergenauigkeit |
|---|---|---|---|
| 1h | 0,306 % | 2,5× | 70,1 % |
| 4h | 0,614 % | 5,1× | 59,9 % |
| 1d | 1,752 % | 14,2× | 53,5 % |
| 7d | 5,099 % | 41,4× | 51,2 % |
| 30d | 11,962 % | 98,5× | 50,5 % |

Die Bewegung ist überall ein Mehrfaches der Kosten. **Also ist Richtung die
bindende Beschränkung, nicht Kosten** — und die niedrigere Latte wurde dann
gemessen: `study_panel.py`, sechs vorab deklarierte Konfigurationen, 3 Märkte,
Tageszeilen, purged walk-forward mit Embargo:

| Horizont | Modell | Richtungsgenauigkeit | 95 % | Basisrate |
|---|---|---|---|---|
| 24h | logistic | 51,28 % | [49,35, 53,37] | 50,43 % |
| 72h | logistic | 51,86 % | [49,41, 54,41] | **52,06 %** |
| 168h | logistic | 49,61 % | [46,28, 52,90] | **51,63 %** |
| 24h | lightgbm | 50,53 % | [48,90, 52,16] | 50,43 % |
| 72h | lightgbm | 49,77 % | [47,67, 51,77] | **52,06 %** |
| 168h | lightgbm | 51,93 % | [49,49, 54,36] | 51,63 % |

**Keines schlägt seine Basisrate.** Bei 72h sind beide Modelle *schlechter* als
„immer long" (52,06 %). Eine niedrigere Latte ist keine übersprungene Latte.

*Methodischer Hinweis, der hier zweimal Geld gekostet hat:* immer gegen die
Basisrate vergleichen, nie gegen 0,5. Und eine Trefferquote ohne ihre Auszahlung
ist kein Ergebnis — bei symmetrischer Auszahlung bräuchte dieses System 66,75 %,
nicht 56,6 %.

### 3.3 Daten — 19 Kandidaten, acht Familien, alle tot

Drei unabhängige Suchprogramme, dieselbe Null. Geprüft und verworfen:
Open Interest, Account-Ratio (long/short), Funding-Raten als Feature,
Liquidationsdaten, Orderflow/Tape, Querschnittsmerkmale, Kalendermerkmale,
Regime-Klassifikation.

Der entscheidende Test: P gegen P+D (Preis gegen Preis plus Derivate) auf einem
**gemeinsamen Fenster**, gepaart. Differenz ±1,6 Punkte, keine konsistente
Richtung, **jedes Intervall über null**. Die Datenherkunft war vorher
verifiziert (ein falscher Docstring hatte diese Achse einen Tag blockiert).

### 3.4 Ausgänge — vier Experimente, vier Fehlschläge

| Experiment | Was | Ergebnis |
|---|---|---|
| E3 | zwei benannte Alternativen zur bestehenden Ausstiegspolitik | bestehende Politik **gewinnt** gegen beide |
| E10 | close-confirmed Stop | Mittelwert besser, **grösster Verlust verdreifacht** |
| E14 | Einstand-Stop bei 1 R / 0,5 R | gefallen; halbiert Voll-R-Verluste (60,3 % → 47,5 % → 31,5 %) und macht das Ergebnis **monoton schlechter** |
| E15 | Zieldeckel bei 1 R / 1,5 R / 2 R | alle drei gefallen |

E14 ist das schärfste Ergebnis des ganzen Projekts: die naheliegende Reparatur
für „der Trade erreicht +1.18 R und endet bei null" **funktioniert messbar
nicht**. Der Rückfall ist also kein Ausstiegsproblem.

### 3.5 Und der Rest

* **Stopweite:** kann das Vorzeichen nicht drehen. Grösse und Hebel kürzen sich,
  der Stop nicht — aber ein 1,5× weiterer Stop hätte 70 % der Trades nicht
  gestoppt, also ändert er den Pfad und nicht nur die Skala. Gemessen: negativ.
* **Einstiegsversatz:** über sechs Stufen **monoton schlechter**
  (−0.0338 R → −0.1075 R bei halber Stopweite), weil der nähere Stop öfter
  trifft.
* **Setup-Auswahl (E16):** das schlechteste Setup (F, 68 Trades bei −0.7503 R,
  54 % des Gesamtverlusts) abschalten → **+0.0061 R, Intervall über null**.
  Gefallen. F bleibt an.
* **Querschnitt:** 5,2 bp/Tag brutto gegen 7,2 bp Umschichtungskosten.
  Reversion **und** Momentum verlieren beide.
* **Carry/Funding:** bestand bei 180 Tagen Halten, **scheiterte an der
  Replikation mit Vorzeichenwechsel**. Das ganze positive Ergebnis liegt vor
  November 2024.
* **Belegungsschatten:** 4.090 verdeckte Signale (2,4× die sichtbaren). Alle zu
  nehmen ist messbar schlecht; ein zweiter Platz ist unentschieden
  (Differenz über null).
* **Trefferquote als Ziel:** zwei Messungen fanden Populationen mit **höherer**
  Trefferquote, die **weniger** verdienen.
* **Wochenende:** eingepreist, nicht gefährlich (18,9 % der Trades gegen 28,6 %
  Kalenderanteil; Wochenendstops 0,724× enger).
* **Makerrolle:** wäre +0.017 R wert — zwölfmal die Venue-Korrektur —, ist aber
  ohne Trade-Tape nicht beweisbar: bis zu 49 % der ruhenden Order verschwinden
  je 17 s unerreicht, und nur **12,4 %** der Order an der Berührung füllen je.
* **Günstige Trades:** haben wirklich besseres **Brutto** (+0.0561 R, Intervall
  über null), nicht nur weniger Kosten. Trotzdem keine Kante — R je Trade
  umspannt die Null.

### 3.6 Der einzige positive Kandidat

Setup A auf D1+H4: **+0.0856 R in-sample**, unter realistischer Ausführung
+0.0728 R. Fünffach zu klein für +0.42 R, und der Pfad kommt erst
**Februar 2027** an. Noch nicht out-of-sample bestätigt.

---

## 4. Die Apparatur — damit du ihre Grenzen kennst

* **Kostenmodell:** maker 0,0200 % Einstieg, maker auf Zielausstieg, taker
  0,0550 % auf Stopausstieg, plus 3 bp Slippage im Budget. Je Fill aus der
  Gebührenspalte rekonstruiert und gegen den Ausstiegsgrund gegengeprüft:
  4.648 Stop → maker/taker, 2.684 Ziel → maker/maker, 3 manuell. Exakt.
* **Wichtig:** der Simulator berechnet die Makergebühr für **jeden**
  Limit-Einstieg, ohne zu prüfen, ob die Makerrolle bewiesen ist. Er rechnet
  also als wäre sie bewiesen — das ist die +0.017 R aus 3.5, und sie liegen
  **zu unseren Gunsten** in allen Zahlen oben.
* **Füllmodell:** pessimistische Intrabar-Auflösung über M1, `fill_on_touch`
  ausgeschaltet (korrekt: nur 12,4 % der Order an der Berührung füllen),
  Entry-Verfall nach 32 Balken.
* **Risiko:** 1 % je Trade, harter Deckel 3 %, Hebel ≤ 10, maximal 5
  gleichzeitige Positionen, Kostendeckel 8 % des Risikos, Mindest-CRV 1,5.
* **Zwei Abnahmekriterien je registriertem Arm:** Bonferroni-korrigiertes
  Intervall ohne die Null **UND** Replikation im Faktor 0,5–2,0.
  `total_comparisons = 73`.
* **Auflösungsgrenze:** ±0.0774 R bei 12 Märkten, ±0.0349 R bei 59,
  ±0.0294 R bei 83. Die Anforderung (+0.42 R) liegt **weit über** der
  Auflösungsgrenze — das Problem ist also **keine Messgenauigkeit**. Mehr Märkte
  helfen nicht.
* **Forschungshygiene, die eingehalten wird:** Zukunfts-Mutationstest über die
  Snapshots, purging und embargo in jedem Walk-forward, Vorwärtsstichprobe
  isoliert und nach Konfigurations- **und** Codestempel getrennt, jede
  Ergebniszeile trägt jetzt eine 18-feldige Herkunftsidentität.

**Zwei bekannte Blindstellen des Apparats, die du in deinem Urteil
berücksichtigen sollst:**

1. Der Zukunfts-Mutationstest verändert nur Balken **nach** dem Index. Er ist
   darum **blind dagegen, dass eine Datenquelle ihre eigene Vergangenheit
   umschreibt**.
2. Der Referenzpreis wurde in den 7.335 Fills nie gespeichert. **Schlupf ist für
   diese Population nicht messbar** — er ist modelliert, nicht gemessen.

---

## 5. Die Fragen, die ich beantwortet haben will

1. **Ist „erschöpft" der korrekte Schluss?** Begründe es an den Zahlen oben, nicht
   allgemein.
2. **Gibt es eine Achse, die nie *gestellt* wurde?** Nicht „nie gemessen", sondern
   **nie gestellt** — eine Grösse, die in jedem Lauf gleich geblieben ist, weil
   niemand sie als Entscheidung erkannt hat. Falls ja: welche, wo wäre sie
   sichtbar, und **welche Grössenordnung** könnte sie plausibel liefern? Ein
   Kandidat, der höchstens 0.01–0.05 R bewegt, löst das Problem nicht — sag das
   dann ausdrücklich.
3. **Ist die Zielrechnung richtig?** +0.42 R über 51 Gelegenheiten, aus Little's
   Law mit der mittleren Haltedauer. Prüfe sie nach. Wenn sie falsch ist, ändert
   sich alles.
4. **Ist der Beta-Befund der eigentliche Befund?** Beta 1,0 auf BTC mit
   verlässlich negativem Residuum heisst: dieses System ist eine gehebelte
   Richtungswette mit negativen Kosten obendrauf. Wenn das stimmt — ist dann
   die ehrliche Alternative „kein System", also schlicht Spot halten?
5. **Was würdest du jetzt tun?** Konkret, mit Begründung, und mit der Option
   „aufhören" als zulässiger Antwort.

**Antworte streng.** Ein Vorschlag, den eine der Zeilen in Abschnitt 3 schon
erledigt, kostet mich Wochen. Wenn du unsicher bist, ob ein Gedanke schon
gemessen wurde: sage, welche Zeile am nächsten liegt, und begründe den
Unterschied.
