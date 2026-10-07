# Eigener Arbeitsplan, 07.10.2026 ~17:30 bis 08.10. ~05:30

Auftrag: zwölf Stunden eigenständig weiterarbeiten, eigene Pläne machen.
Dies ist der Plan. Er wird am Ende gegen das Ergebnis gelesen, nicht
nachträglich an es angepasst.

## Der Stand, von dem aus geplant wird

Nichts in diesem System hat einen belegten Vorteil. 19 Familien gemessen,
keine positiv. FreqAI je Trade schlechter als die Basislinie. Die
Bewertung ohne Informationsgehalt. Der Carry war bis November 2024 ein
Ertrag und ist seither keiner. Das sind keine Rückschläge, die man durch
Fleiss aufholt — das ist der Befund.

Genau **eine** Grösse hat sich zugunsten des Systems bewegt: die
Ausführungskosten auf der neuen Venue (BTC-Taker-Runde 0,0005 %, 22× unter
der Obergrenze des gemessenen Einstiegsvorsprungs). Ob sich dort ein Signal
überträgt, ist die einzige offene Frage mit positivem Vorzeichen.

Daraus folgt die Reihenfolge, und sie ist nicht beliebig.

## 1. Die Aufnahme — zuerst, weil sie Wartezeit ist (LÄUFT seit ~17:30)

`scripts/collect_venue_tape.py --hours 11`

Der eine nächste Schritt aus Abschnitt 18 des Zustandsberichts. Drei
offene Punkte hängen an derselben Aufnahme: E0 Punkt 3, S7 und E5.

**Was den Blocker aufhebt:** `recentTrades` liefert `ask_id` und `bid_id`,
die Order-Kennungen beider Seiten. Damit lässt sich eine im Buch
beobachtete Order in den Trades wiederfinden — und genau das war
unmöglich. `study_venue_fills.py` musste 33 von 41 Verkleinerungen als
nicht belegbar verwerfen, weil eine geschrumpfte `remaining_base_amount`
auch eine Teil-Storno sein kann. Mit der Kennung ist ein Fill ein Fill.

Beim Bauen zwei eigene Fehler gefangen, beide vom Typ „Kennzahl, die immer
dasselbe sagt":

* Der Lückenzähler rechnete die Differenz der `trade_id` als Trade-Zahl und
  meldete **97 % Verlust**, wo keiner war — die Kennung läuft *global* über
  alle Märkte. Jetzt werden Lücken-*Ereignisse* gezählt und ausdrücklich
  gesagt, dass die Anzahl fehlender Trades aus diesen Daten nicht folgt.
* „Volle Seite" prüfte `len(trades) >= 100` und meldete 24 von 24 — die API
  gibt 100 zurück, wenn man 100 anfragt. Jetzt auf den *neuen* Zeilen.

Dazu: der Takt ist **adaptiv**, weil eine einmal gemessene Rate nicht
reicht. ETH las 3,72 Trades/s und lief im Probelauf mit 10,6 über. Bei
voller Seite oder Lücke halbiert sich das Intervall, bei dünner Seite
wächst es. Und die Datensätze sind auf 12 von 31 Feldern gekürzt: 308
statt 1 054 Bytes je Trade, weil das Ganze in einem synchronisierenden
OneDrive-Ordner liegt.

## 2. Die Vorwärts-Evidenz schützen

Der Papierhändler hatte 58 gescheiterte Zyklen, alle an
`fetch_ohlcv(SYMBOL, W1)`. Er ist die *einzige* Quelle von
Vorwärts-Evidenz; jeder gescheiterte Zyklus ist eine Entscheidung, die
nicht getroffen wurde. Ursache finden und beheben.

## 3. E3 — Ausgänge als kausale Handelspolitik

Angemeldet, nicht blockiert, drei Arme. Und auf logischen Gründen der
aussichtsreichste verbliebene Arm: `stop-width-cannot-flip-the-sign` hält
fest, dass Grösse und Hebel sich herauskürzen, **der Stop aber nicht** — er
verschiebt den Ausstieg und damit den Pfad. Eine andere Exit-Politik auf
denselben Entries ist also eine echte andere Frage, nicht eine Skalierung.

Arme: bisheriger Stop/TP · Stop mit festem Zeitausstieg (24 h) ·
ATR-Trailing (2,0 ATR, vorab fix). Abnahme: gepaarter Mehrwert auf
denselben Entries, danach Portfolio-Replay.

## 4. E7 — die kostenlosen Arme

E7.1 (kein Urteil), E7.2 (FakeBrain), E7.3 (kalibriertes Modell aus E1)
kosten nichts. Nur E7.4 (echtes Claude-Urteil) kostet API-Geld, und der
Auftrag sagt ausdrücklich: Kosten als Budgetvorschlag berichten, keine
Käufe daraus ableiten. Also werden die drei freien Arme gerechnet und
damit die Latte festgelegt, die der bezahlte Arm überspringen müsste.
**Ich gebe autonom kein API-Budget aus.**

## 5. E4 — Machbarkeit des Point-in-Time-Universums

Blockiert durch Survivorship. Prüfen, ob historische Symbollisten aus dem
Binance-Archiv zu bekommen sind. Wenn ja, ist E4 entsperrt; wenn nein,
steht der Grund belegt im Manifest statt als Vermutung.

## 6. Die Aufnahme messen (am Ende, ~04:30)

`study_venue_fills.py` auf den Trade-Join erweitern: belegte Fills, belegte
Stornos, echte Markouts mit Aggressor-Vorzeichen. Das ist die Antwort auf
S7 und auf F3 des Forschungsauftrags.

## Was ich in diesen zwölf Stunden NICHT tue

* **Kein API-Budget ausgeben.** E7.4 bleibt ein Vorschlag mit Preisschild.
* **Die Währung nicht umbenennen.** Konten sagen CHF, Preise sind USDT,
  eine Umrechnung existiert nicht. Das ist dem Nutzer gemeldet und ist
  seine Entscheidung, nicht die eines Patches.
* **Keine Schutzregel anfassen.** 3 % harte Grenze, 1,2-s-Bestätigung,
  `testnet=False` und `allow_live=True` getrennt, keine Handelsrechte auf
  der neuen Venue. `binance_spot` bleibt in `DATA_ONLY`.
* **Kein Erfolgskriterium nach dem Ergebnis ändern.** Beide Tore bleiben:
  korrigiertes Intervall ohne Null **und** Replikation 0,5–2,0×. E6 ist
  gerade der Fall, der zeigt warum — es passierte das erste und fiel am
  zweiten.
* **Keine Zahl ohne ihr Intervall berichten**, und keinen Einzelmarkt als
  Eigenschaft des Systems.

## Wie das hier endet

Mit einem Ergebnis, nicht mit Aktivität. Wenn die Aufnahme zeigt, dass
sich das Signal nicht überträgt, ist das das Ergebnis dieser zwölf
Stunden — und es ist mehr wert als ein weiterer Kandidat, der am zweiten
Tor fällt.

---

## Fortschritt, gegen diesen Plan gelesen (Stand 18:10 UTC, ~1h gearbeitet)

| # | Punkt | Stand |
|---|---|---|
| 1 | Tape-Aufnahme | **läuft**, 25 MB, 13 Lücken auf ~425 Abfragen (~3 %) |
| 2 | Vorwärts-Evidenz schützen | **erledigt** — die 58 Fehlschläge waren historisch (zwei Händler, doppelte Anfragerate), und der Zähler verschwieg es |
| 3 | E3 Ausgänge | **erledigt, negativ** — und die bestehende Politik erstmals *verteidigt* |
| 4 | E7 freie Arme | **umdisponiert** zu `audit/E7_BUDGETVORSCHLAG.md`, Begründung dort |
| 5 | E4 Machbarkeit | **übererfüllt** — nicht geprüft, sondern gebaut; E4 ist entsperrt |
| 6 | Aufnahme messen | **Maschinerie fertig und validiert**, wartet auf Daten |

### Was ich gegen den Plan anders gemacht habe, und warum

**Punkt 4 habe ich nicht gerechnet.** Der Plan sagte, die freien Arme E7.1–E7.3
kosten nichts und legen die Latte fest. Beim Nachsehen stellte sich heraus:
der Signalpfad konsultiert FakeBrain überhaupt nicht — die gespeicherte
Bewertung kommt von `rate(score_at(...))`. E7 bräuchte also einen neuen
Harness über Snapshots, für ein nach drei vorhandenen Messungen
vorhersehbares Null-Ergebnis, während eine zeitkritische Aufnahme läuft.

Das war die schlechtere Verwendung der Stunde. Stattdessen steht jetzt die
**Latte und ihr Preisschild** da, und das ist die Zahl, die der Nutzer
braucht: ein bezahlter Arm kostet 49 bis 2 672 USD, also **5 % bis 267 % des
gesamten Kontos** für eine Messung.

Das ist eine Abwägung, keine Erledigung, und E7 bleibt im Register
registriert.

**Punkt 5 ist über den Plan hinausgegangen.** Geplant war zu *prüfen*, ob ein
Point-in-Time-Universum beschaffbar ist. Es war beschaffbar, also habe ich es
gebaut — 31 echte Perp-Delistings von 906, alle mit letztem Archivtag. Eine
geprüfte Machbarkeit, die man danach noch bauen muss, ist eine halbe Antwort.

### Fünf eigene Fehler in dieser Stunde

Vier davon hatten dieselbe Form: **die Kennzahl beschrieb den Apparat, nicht
die Welt.** 97 % Trade-Verlust (globale `trade_id`), 24-von-24 volle Seiten
(die API gibt, was man anfragt), 8,1 % Survivorship (46 abgelaufene
Quartalsfutures mitgezählt), 99,5 % Lücken (die Dateien enthalten nur das
Neue). Faktoren: unendlich, konstant, 2,4×, 33×.

Der fünfte war anderer Art und der teuerste: der Collector starb nach genau
zehn Minuten an einem umbenannten Feld im Fortschrittsvermerk. Drei
Rauchtests grün, Linter grün, tot an der ersten Zeile, die keiner davon
erreicht hat. **Ein Codepfad, dessen Auslöser länger ist als der Test, ist
ungetestet.**

### Was bis ~04:00 UTC bleibt

Warten auf die Aufnahme, und dann Punkt 6 mit echten Daten. Zehn Stunden
Tape statt 32 Minuten ist der Unterschied zwischen „die Maschinerie
funktioniert" und „so verhält sich diese Venue".
