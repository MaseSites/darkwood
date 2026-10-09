# Plan für fünf Stunden Alleinarbeit

Angelegt 09.10.2026, 12:05 UTC. Commit `2dd34ef`.

Reihenfolge nach Wert, nicht nach Bequemlichkeit. Was lange messen muss, läuft
zuerst an.

---

## Selbst auferlegte Regeln

Dieselben wie in `PLAN_12H.md`, und sie gelten weiter:

1. **Kein API-Budget** ausgeben.
2. **Keine Schutzregel anfassen.** Risiko-Deckel, 1,2-Sekunden-Bestätigung,
   `testnet`/`allow_live` getrennt — unberührt.
3. **Kein Erfolgskriterium nach dem Ergebnis ändern.** Beide Tore bleiben.
4. **Keine Zahl ohne ihr Intervall.** Kein einzelner Markt als Eigenschaft des
   Systems.
5. **Keinen zweiten Papierhändler starten.** Der Lock verhindert es jetzt, aber
   die Regel steht trotzdem.
6. **Kein Weg um eine Börsenbeschränkung herum.**
7. **Jede neue Vergleichszelle vorher anmelden**, auch wenn sie klein aussieht.

## Die Punkte

### 1. Die 110 unaufgezählten Versuche rekonstruieren

`TRIAL_LEDGER.csv` hat gezeigt: `meta.prior_search` behauptet 124 Versuche und
87 Arme, aufzählbar sind 14. Die Differenz ist ein Dokumentationsmangel, den
ich selbst gefunden habe und der sich schliessen lässt — aus der Git-Historie
und den Audit-Berichten.

**Abnahme:** jede Zeile im Ledger trägt eine Quelle, die sich öffnen lässt.
Was sich nicht belegen lässt, bleibt als Lücke stehen und wird nicht geraten.

### 2. Warum W1

Der Fehler-Ausbruch vom 09.10. traf **ausschliesslich** `fetch_ohlcv(..., W1)`
— den ersten Abruf jedes Zyklus. Dass es der erste ist, ist eine Beobachtung
und keine Erklärung. Messbar: Latenz je Zeitebene über ein langes Fenster.

**Läuft zuerst an**, weil es Zeit braucht.

**Abnahme:** eine Verteilung der Antwortzeiten je Zeitebene, und eine Aussage
darüber, ob W1 systematisch langsamer ist oder nur zuerst dran.

### 3. Ein Arm mit kleinerem Umschlag

E4V hat notiert, was die Arithmetik **nicht** ausschliesst: *„ein Signal mit
deutlich grösserem Brutto oder deutlich kleinerem Umschlag."* Das Brutto war
5,20 bp/Tag, die Maut 7,15. Bei wöchentlicher statt täglicher Umschichtung
fällt die Maut auf ein Siebtel.

**Vorher anzumelden**, weil E4V ausdrücklich „kein zweiter Horizont in diesem
Schirm" festgelegt hat.

**Nicht wiederzubeleben:** die früheren Arme `mom_7`, `mom_30`, `vol_30` sind
gemessen und tot. Der Unterschied bleibt die Faktorbereinigung.

**Abnahme:** beide Tore, und die Einzelmarkt-Prüfung wie bei E4V.

### 4. Veraltete Daten sollen Signale sperren

Phase 1 Punkt 5 des Forschungsauftrags, der einzige Punkt daraus, der ohne
Streaming erfüllbar ist. Heute **meldet** der Papierhandel eine erhöhte
Fehlerquote (seit heute), aber kein Signal wird daraufhin gesperrt. Ein
Entscheid auf veralteten Kerzen ist ein Entscheid auf Daten, die es nicht gibt.

**Abnahme:** ein Test, der künstlich veraltete Daten einspeist und belegt,
dass kein Einstieg daraus entsteht.

## Was ausdrücklich NICHT auf dem Plan steht

| | Grund |
|---|---|
| E5 / P26 | blockiert an Marktdaten für diese IP, nicht an Code |
| E4 selbst | blockiert an Kursen für ein Punkt-in-Zeit-Universum |
| E7 mit API-Aufrufen | kostet Budget; die Reproduktion bestehender Fälle ist erlaubt, ein neuer Lauf nicht |
| mehr Märkte, Indikatoren, Hebel, Trades | gemessen erledigt |
| Live-Handel in jeder Form | gesperrt, und P33 ist offen |

## Protokoll

**12:05** Plan angelegt. Latenz-Messung (Punkt 2) angelaufen, 150 Minuten.

**12:40 — Punkt 1 erledigt.** Die 110 unaufgezählten Versuche schrumpfen auf
**12**. Die Spur waren `data/study_*.json`: sie speichern je Zelle die
vollständige R-Reihe, also 59 nachrechenbare Zellen. Dazu 14 berichtete
(`ratchet.TRIED`) und 39 benannte Studien ohne Ergebnisdatei. Und die 59 neu
gerechneten bestätigen den Befund unabhängig: 6 positive Mittel, **0 mit
Intervall ohne Null**, beste Zelle +0,0455 R gegen +0,7280 verlangt.

**13:20 — Punkt 3 erledigt, E4W.** Die Maut fällt um Faktor 5, das Brutto
nicht. Die vorab festgelegte Tötungsbedingung ist damit **nicht** erfüllt —
der Querschnitt trägt Information je Zeit. Beide Tore fallen trotzdem, und
die Nachrechnung schliesst die Frage: es bräuchte **31,9 Jahre** Kalenderzeit
(oder 11,1 unkorrigiert), vorhanden sind 6,1, und Perps gibt es seit sieben.
**Nicht entscheidbar**, nicht nur unentschieden.

**13:35 — Punkt 4 erledigt.** Veraltete Daten sperren jetzt ein Signal. Der
Fehlschlag-Pfad war schon sicher; nicht sicher war eine *gelungene* Abfrage
mit altem Balken, die mit `!=` den Zeiger rückwärts gesetzt hätte.

**13:37 — und dann habe ich den Papierhandel abgestürzt.** Beim Neustart, der
die drei Verbesserungen holen sollte, warf mein eigener `FailureWatch`
`AttributeError: 'PaperTrader' object has no attribute 'tally'`. Der Zähler
sitzt unter `stats.tally`; meine Test-Vorrichtung trug ihn oben. **Sechs
Tests grün, Code falsch.**

Behoben um **13:43**, Ausfall rund acht Minuten, verloren nichts (der Broker
holt 240 Minuten nach; die Minute 13:36 war beim Neustart 13:47 aufgeholt).
Dazu der Test, der gefehlt hat: einer, der das **echte** `PaperTrader`-Objekt
anfasst statt eine Vorrichtung.

**13:48** Papierhandel gesund, +23 Zyklen in 75 s, Lock gehalten,
`stale_bars` 0.

**15:15 — eine Korrektur, die nicht auf dem Plan stand.** Beim Warten auf die
Latenzmessung geprüft, ob die Vorwärtsstichprobe *eine* Stichprobe ist. Sie
war es nicht, und zwar zweimal nicht: nach dem Konfigurationsschnitt (18 → 14)
kamen noch zwei **Code**-Änderungen, die verändern, welche Trades entstehen,
und **keine davon bewegt `run_signature`**. Homogen sind **11 Trades**,
+0,7867 R, Intervall [−1,043; +1,976]. Termin **24.10.2026**. Der Mittelwert
steigt mit jedem Schnitt — als Gefahr benannt, nicht als Ergebnis.
`JournalEntry` trägt jetzt beide Felder: Signatur *und* Commit, weil keines
allein entscheidet.

**15:44 — Punkt 2 erledigt, und die Antwort lautet „nicht W1".** 1 415 Abrufe
über 2,5 Stunden, Reihenfolge gedreht. Streuung über **Zeitebenen 3 ms**, über
**Positionen 37 ms** — der erste Abruf eines Zyklus zahlt 36 ms, die Ebene ist
gleichgültig. Die Abnahme ist erfüllt: eine Verteilung je Ebene liegt vor, und
die Aussage ist eindeutig.

**Und sie erklärt den Ausbruch nicht.** ccxt bricht bei 10 000 ms ab; der
schlechteste von 1 415 Abrufen war 840 ms, Faktor zwölf darunter. Der
Kaltstart verschiebt den Körper der Verteilung und fügt **keinen Rand** hinzu
— ein Timeout ist ein Randereignis. Das ist Evidenz *gegen* den einzigen
Mechanismus, den die Messung sehen konnte, nicht bloss zu wenig davon.

**Zwei Beinahe-Fehler dabei, beide vom Typ „was ich nie variiert habe".**
Erst hielt ich den gemessenen Host für den falschen: `settings.yaml` sagt
`testnet: true`, und der Testnet-Host ist tatsächlich 1,9× langsamer — das
**Elffache** des Positionseffekts. Zwanzig Minuten war das mein Ergebnis, bis
`papertrade.py:105` mit `testnet=False` und einer Begründung dastand. Die
Messung war richtig; die Grösse mit dem stärksten Effekt war konstant
richtig **aus Glück**. Zweitens: das Skript rechnete 1 415 Messungen in eine
Zusammenfassung und verwarf sie. Behoben für den nächsten Lauf, für diesen
nicht nachholbar.

Und ein Kandidat, der ausdrücklich **nicht** umgesetzt wird: ein Aufwärm-Abruf
würde Position 1 entlasten — und die Vorwärtsstichprobe zurücksetzen, ohne
dass `run_signature` es aufzeichnet. Nach den 41 Trades, nicht davor.

## Bilanz der fünf Stunden

| Punkt | Stand |
|---|---|
| 1 — die 110 unaufgezählten Versuche | **erledigt**, 110 → 12, und 59 Zellen unabhängig nachgerechnet |
| 2 — warum W1 | **erledigt**, Antwort: nicht W1. Der Ausbruch bleibt unerklärt, jetzt richtig gestellt |
| 3 — Arm mit kleinerem Umschlag (E4W) | **erledigt**, beide Tore gefallen, und **nicht entscheidbar**: 31,9 Jahre nötig, 6,1 vorhanden |
| 4 — veraltete Daten sperren Signale | **erledigt**, mit Test; dabei einen Rückwärts-Zeiger gefunden, der stillgeschwiegen hätte |

Dazu ungeplant: ein OS-Lock gegen zwei Papierhändler, eine Fehlerquoten-Wache
(die mich erst einmal acht Minuten Ausfall gekostet hat), `code_version` und
`run_signature` im Journaleintrag, und die Stichprobenkorrektur auf 11.

**Kein Kandidat gefunden.** Das war auch nicht der Plan — die vier Punkte
waren Messungen und Absicherungen, keine Suche. Die einzige Evidenzquelle,
die noch wächst, ist der Vorwärtslauf, und der braucht 30 weitere Trades.
