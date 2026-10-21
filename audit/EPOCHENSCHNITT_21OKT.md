# Epochenschnitt 21.10.2026, 09:44:36 — `max_same_direction` wird scharf

**Warum dieser Zettel existiert.** `decision_version()` wird beim **Schliessen**
eines Trades geschrieben, nicht beim Eröffnen. Ein Neustart des Händlers mit
offenen Positionen schlägt diese darum der **neuen** Epoche zu, obwohl die neue
Regel bei ihrer Eröffnung nichts zu sagen hatte.

Vier Positionen waren offen. Sie gehören zur **alten** Epoche, und jede
Auswertung der neuen muss sie ausschliessen.

## Der Schnitt

```
Zeitpunkt      1792568676383   (21.10.2026 09:44:36 lokal)
Stempel alt    4dec6f76e62e
Stempel neu    599d3242fbcb
Signatur       …|plan30x7r15f   (unverändert — die Grenze steht in risk.yaml,
                                 nicht in der Grössenregel)
```

## Die vier Positionen, die den Schnitt überleben

| Markt | Seite | Menge | Einstieg | Setup | offen seit |
|---|---|---|---|---|---|
| ETHUSDT | long | 0.728 | 2'451.53 | A | 09:31 |
| AVAXUSDT | short | 134.0 | 9.707 | B | 04:15 |
| LINKUSDT | long | 145.64 | 12.411 | A | 09:30 |
| ATOMUSDT | long | 540.59 | 1.738 | G | 21:30 (Vortag) |

**Regel für jede Auswertung der neuen Epoche:** Trades mit
`opened_ts < 1792568676383` ausschliessen, auch wenn ihr `decision_version`
auf `599d3242fbcb` lautet. Es sind genau diese vier.

## Warum nicht auf einen flachen Moment gewartet wurde

Es gab keinen. Bei 26 Trades am Tag über zwölf Märkte und einer mittleren
Haltedauer von 31 Minuten öffnet eine Position, während die nächste schliesst;
das Konto war über zwei Stunden Beobachtung nie unter vier offenen. Ein
Wartelauf auf null lief ins Leere.

Die Alternative — die Grenze unbegrenzt ausgeschaltet lassen — wäre teurer
gewesen als vier dokumentierte Zeilen.

## Was der Schnitt bemerkenswert macht

**Drei der vier offenen Positionen sind long.** Die Grenze, die ab jetzt gilt,
hätte die dritte bereits verhindert — ETHUSDT (09:31) oder LINKUSDT (09:30),
je nachdem welche zuerst kam. Der Fall, für den sie gebaut wurde, lag im
Moment ihres Scharfschaltens auf dem Tisch.

## Der eigentliche Mangel, und was dagegen zu tun wäre

Dass dieser Zettel nötig ist, ist der Mangel. Richtig wäre, den Stempel beim
**Eröffnen** festzuhalten und beim Schliessen den festgehaltenen zu schreiben.
Das verlangt ein Feld im dauerhaften Zustand (`live/paperstate.py`), denn ein
Wert im Arbeitsspeicher überlebt genau den Neustart nicht, um den es hier geht.

Nicht jetzt gemacht, und der Grund ist abwägbar: `paperstate` liegt im
Entscheidungspfad, und eine Schemaänderung am gespeicherten Zustand kann einen
laufenden Händler daran hindern, seinen eigenen Zustand zu lesen. Das wäre ein
Ausfall gegen einen Buchhaltungsmangel getauscht.

**Vorgemerkt** für den nächsten geplanten Stillstand, nicht für einen
Zwischendurch-Neustart.
