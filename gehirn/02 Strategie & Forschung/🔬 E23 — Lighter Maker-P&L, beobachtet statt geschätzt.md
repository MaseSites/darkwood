---
typ: forschung
status: entschieden
aktualisiert: 2026-10-21
naechster_schritt: dasselbe Programm über eine Woche, und Konten verfolgen statt aggregieren
tags: [market-making, lighter, adverse-selektion, e23, e20-ueberholt]
---

# 🔬 E23 — Lighter Maker-P&L, beobachtet statt geschätzt

974'938 Geschäfte, 24 h, drei Märkte. Vollbericht: `audit/E23_LIGHTER_MAKER_PNL.md`
Nachrechnen: `python scripts/study_lighter_pnl.py`

## Warum diese Frage anders beantwortbar war als jede andere

Lighters Websocket nennt bei jedem Geschäft **beide Konten**, welche Seite der
Maker war und den **Bestand beider Seiten davor**. Damit wird „lohnt sich
Market Making hier?" zu einer **Beobachtung** statt einer Schätzung — man
sieht, ob andere damit Geld verdienen, bevor man einen Rappen einsetzt.

In diesem Projekt einzigartig. Jede andere Frage brauchte eine eigene
Stichprobe und damit eigenes Risiko.

## Der Befund: der gestellte Spread ist nicht der behaltene

Realisierter Spread, driftbereinigt, in bp auf gehandeltes Nominal:

| Horizont | BTC | ETH | SOL |
|---|---|---|---|
| sofort | **+0.320** | **+0.555** | **+0.333** |
| +10 s | +0.058 | **−0.223** | **−0.280** |
| +60 s | +0.236 | **−0.362** | −0.092 |
| +300 s | +0.283 | −0.190 | −0.094 |

> [!important] BTC-Maker behalten ihren Spread. ETH und SOL geben ihn binnen
> zehn Sekunden vollständig zurück.
> Auf ETH: +0.555 bp gestellt, nach 10 s −0.223 bp. **0.78 bp Rückgabe gegen
> 0.56 bp Einnahme.** Das ist adverse Selektion, und sie ist das 8- bis
> 28-fache der Gebühr.

**Nicht die Gebühr ist der Preis des Market Making, sondern diese Differenz.**

## Das überholt E20 — und der Grund ist lehrreich

[[🧪 Experimentregister]] führt E20 mit dem Schluss *„BTC ist tot, ETH und SOL
sind es nicht."* Grundlage war der **gestellte** Touch-Spread: BTC 0.0244 bp
gegen ETH 0.4585 und SOL 0.4807 bp.

Hier gemessen ist es **umgekehrt**. Der Unterschied ist der zwischen

- was man **stellt** (Touch-Spread) und
- was man **behält** (realisierter Spread).

Ein weiter Spread auf einem Markt, auf dem informierter Fluss ihn sofort
abholt, ist kein Verdienst, sondern eine Einladung.

E20 ist nicht falsch gerechnet — es hat die falsche Grösse gemessen.

## Die Zerlegung, ohne die man Richtung als Handwerk liest

Alle drei Märkte stiegen im Fenster. Exakt aufgeteilt:

| Markt | Kurs | P&L der Maker | Ausführung | Altbestand |
|---|---|---|---|---|
| BTC | +2.52 % | +349'205 (+4.47 bp) | **+275'696** | +73'509 |
| ETH | +3.14 % | −357'424 (−7.34 bp) | −60'044 | **−297'380** |
| SOL | +4.33 % | +43'176 (+6.07 bp) | **−21'186** | +64'362 |

**SOL sieht profitabel aus und ist es nicht:** das Handwerk verlor, die Rallye
rettete es. Ohne diese Zerlegung liest man genau das als Können.

## Zwei Fehler in der eigenen Messung, beide gefunden

1. `bisect_left` traf bei Horizont 0 denselben Zeitstempel — viele Geschäfte
   teilen sich einen (ein Taker räumt mehrere Ebenen ab). Die Messung las
   damit die Sweep-Tiefe statt „was danach geschah".
2. Die erste „Bereinigung" addierte den **Betrag** der Drift. Das ist keine
   Korrektur, sondern eine Erfindung — aus +0.30 bp wurde +3.71 bp. Richtig
   ist `Seitenungleichgewicht × Drift`.

## Was NICHT folgt

Dass wir es tun sollten. Zwischen „andere verdienen hier" und „wir können es"
steht die **Füllquote von 2.880 %** [2.396, 3.444] aus E20 — und die wurde
nicht für jemanden gemessen, der neu dazukommt und keinen Latenzvorteil hat.

## Verwandt

[[🧪 Experimentregister]] · [[📊 Evidenzstand]] · [[🔌 Venue & Execution]] ·
[[💸 Verlustanalyse Plankonto — 21.10.2026]]
