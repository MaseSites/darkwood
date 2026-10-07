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
