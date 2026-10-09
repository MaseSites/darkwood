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

Wird in diesem Dokument fortgeschrieben, mit Zeitstempeln.
