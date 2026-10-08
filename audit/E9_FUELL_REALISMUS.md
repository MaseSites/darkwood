# E9 — Unsere Füll-Annahme ist zu streng, nicht zu grosszügig

Reproduktion:

```bash
python scripts/study_fill_realism.py --markets BTC,ETH,SOL,XRP,DOGE,LINK
```

Angemeldet als Arm E9 am 08.10.2026, vor dem ersten Lauf. `total_comparisons`
48 → 49, Niveau 99.8980 %.

---

## 1. Warum nicht gegen Liquids Paper-Modus gemessen wurde

Die Aufgabe lautete, unseren Simulator gegen Liquid Co-Invest Paper Trading zu
stellen. Das geht nicht, und zwar aus vier Gründen, die alle vor der ersten
Zahl feststehen:

**Liquids Füllmodell ist nicht dokumentiert.** Geprüft auf
`liquid.trade/coinvest-docs` und `docs.tryliquid.xyz`. Dokumentiert ist: *„a
simulated balance of $10,000 running against live market data — real prices,
fake money"*. Nicht dokumentiert: wie eine Limit-Order füllt, ob auf
Berührung, auf Durchhandeln, nach Warteschlange oder sofort am Mid; kein
Slippage-Modell; keine Preisquelle. **Ein Unterschied gegen eine Blackbox
sagt, dass zwei Modelle sich unterscheiden — nicht, welches recht hat.**

**Es gibt kein Replay.** Liquid Paper läuft gegen Live-Marktdaten. Unsere
Journal-Trades sind historisch — 2 734 aus dem Replay, 14 vorwärts vom 02. bis
08.10. Dieselben Einstiege „in beiden simulieren" ist für keinen einzigen
bestehenden Trade möglich.

**Die Gebühren würden den Vergleich dominieren.** Liquid Tier 0 für
Krypto-Perps: **Taker 0,095 %, Maker 0,065 %.** Unser Simulator rechnet mit
0,055 % und 0,02 %. Das ist das 1,7- bzw. **3,25-fache**. Eine PnL-Differenz
zwischen den beiden wäre eine Gebührendifferenz, nicht eine Fülldifferenz.

**Und technisch:** unser Papierhändler ist ein Python-Prozess, der alle 60
Sekunden entscheidet. Er kann kein MCP aufrufen. Liquids Paper-Modus wird aus
einer Chat-Sitzung bedient.

## 2. Wogegen stattdessen — und es ist besser

Gegen das aufgenommene Tape der neuen Venue. Dort ist eine Füllung **belegt**
statt modelliert: das Buch trägt `order_id`, die Trades tragen `ask_id` und
`bid_id`. Eine Kennung, die in einem Trade auftaucht, ist gehandelt worden.

Das ist kein zweiter Simulator. Das ist die Börse.

Für jede beobachtete ruhende Order:

```
unsere Regel sagt "gefüllt"   ⟺  während ihrer Lebenszeit druckte ein Trade
                                  STRENG jenseits ihres Preises
die Wirklichkeit sagt         ⟺  ihre Kennung steht in einem Trade
```

## 3. Das Ergebnis — und es ist das Gegenteil der Sorge

**657 647 beobachtete Orders, sechs Märkte, 981 Buchaufnahmen** (volle
11-Stunden-Aufnahme). Die Tabelle unten stand zuerst auf 545 344 Orders aus
9,5 h; auf der vollen Aufnahme ist die gepoolte Rate **0,6 % [0,6; 0,7]** —
**unverändert, Verhältnis 1,00×.**

| Markt | Orders | Falschfüllung | verpasst |
|---|---|---|---|
| BTC | 179 134 | 0,8 % [0,7; 0,9] | 95,0 % |
| ETH | 172 280 | 1,1 % [1,0; 1,2] | 87,5 % |
| SOL | 138 462 | 0,5 % [0,4; 0,6] | 96,4 % |
| XRP | 74 574 | 0,2 % [0,1; 0,3] | 97,5 % |
| DOGE | 55 633 | 0,1 % [0,0; 0,1] | 93,7 % |
| LINK | 37 564 | 0,1 % [0,0; 0,3] | 99,5 % |
| **gepoolt** | **657 647** | **0,6 % [0,6; 0,7]** | — |

Am Antritt (0–1 bp) füllen **12,4 %** der echten Orders — vorher 12,9 %.

### Und das ist die Pointe im Vergleich mit dem Rest der Aufnahme

Vier Grössen wurden auf voller Abdeckung neu gemessen:

| Grösse | 3,2–9,5 h | 11 h | Verhältnis |
|---|---|---|---|
| **E9 Falschfüllung** | 0,6 % | 0,6 % | **1,00×** |
| Taker-Drift BTC 1 s | +0,078 bp | +0,086 bp | 1,10× |
| Maker-Markout BTC 1 s | −0,195 bp | −0,083 bp | **0,43×** |
| Niveau-Differenz | +0,342 bp | −0,504 bp | **Vorzeichen** |

Die Ordnung ist kein Zufall: E9 und die Taker-Drift rechnen über das **ganze
Tape**, der Maker-Markout und die Niveau-Differenz über eine **Auswahl**.
Siehe `audit/TAPE_VOLLE_ABDECKUNG.md`.

---

**Die ursprüngliche Tabelle, 9,5 h, unverändert:**

| Markt | Orders | belegt gefüllt | **Falschfüllung** | **verpasst** |
|---|---|---|---|---|
| BTC | 148 823 | 7,1 % | **0,8 %** [0,7; 0,8] | 95,0 % |
| ETH | 143 818 | 4,0 % | **0,6 %** | 94,6 % |
| SOL | 113 818 | 3,3 % | **0,5 %** [0,4; 0,6] | 95,9 % |
| XRP | 61 658 | 0,6 % | **0,2 %** [0,1; 0,3] | 97,5 % |
| DOGE | 46 092 | 0,4 % | **0,1 %** | 95,2 % |
| LINK | 31 135 | 0,5 % | **0,1 %** | 99,3 % |
| **gepoolt** | **545 344** | — | **0,6 %** [0,6; 0,7] | — |

**Falschfüllung 0,6 %.** Von 524 547 Orders, die nie gehandelt wurden, hätte
unsere Regel 3 337 als gefüllt verbucht. Unser Simulator erfindet praktisch
keine Füllungen.

Das hat einen Grund, und er ist logisch zwingend: wenn ein Trade **jenseits**
eines Preises druckt, wurde alles an diesem Preis aufgebraucht. Wer dort
stand, wurde gefüllt. `fill_on_touch: false` ist keine vorsichtige Schätzung,
es ist fast eine Implikation.

**Verpasst 95–99 %.** Umgekehrt sagt unsere Regel „nicht gefüllt" für
praktisch jede Order, die wirklich gefüllt wurde. Auch das ist zwingend: ein
Maker wird gefüllt, wenn jemand **bei** seinem Preis handelt — nicht jenseits.
Unsere Regel verlangt jenseits.

### Nach Abstand vom Mid

| Abstand | n | belegt gefüllt | Regel sagt ja | Falschfüllung |
|---|---|---|---|---|
| 0–1 bp | 73 544 | **12,9 %** | 0,8 % | 0,4 % |
| 1–5 bp | 290 108 | 3,2 % | 1,2 % | 0,9 % |
| 5–20 bp | 143 771 | 1,2 % | 0,5 % | 0,4 % |
| 20–100 bp | 34 839 | 0,8 % | 0,3 % | 0,3 % |
| > 100 bp | 3 082 | 0,8 % | 1,1 % | 1,1 % |

Die Zeile, die eine Umstellung auf `fill_on_touch: true` verbietet: **selbst
direkt am Antritt füllen nur 12,9 % der echten Orders.** Eine Regel, die bei
Berührung füllt, wäre um ein Vielfaches zu grosszügig.

## 4. Was daraus folgt — und was nicht

**Folgt:** unser Simulator ist auf der Füllseite **konservativ, nicht
optimistisch**. Die Sorge, dass wir uns Einstiege schönrechnen, die es nicht
gegeben hätte, ist mit 0,6 % Falschfüllung nicht haltbar.

**Folgt nicht, und das ist die Versuchung an dieser Stelle:** dass das System
in Wahrheit besser ist als gemessen. Der Gedankengang wäre: unsere Regel
verweigert Einstiege, bei denen der Preis das Level berührt und umkehrt — und
bei einem Short-Einstieg oberhalb des Marktes ist genau das der *beste*
Einstieg. Wir nähmen also bevorzugt die Trades, bei denen der Preis
durchläuft, und das sind die Verlierer.

Das ist eine **Hypothese mit benannter Richtung**, keine Messung. Sie gehört
gemessen, nicht geglaubt.

**Und eine Zahl begrenzt ihre Dringlichkeit sofort.** Im laufenden
Vorwärtsbetrieb:

```
  proposed          105
  refused_by_risk    86
  opened             19
  expired             0
```

**Keine einzige wartende Einstiegsorder ist je unbefüllt verfallen.** Alle 19,
die durch die Risk Engine kamen, wurden gefüllt. Der Flaschenhals ist die
Risikoprüfung, nicht die Füllung. Für den Vorwärtslauf ist die Frage bisher
ohne Wirkung; sie betrifft die Replay-Population.

## 4b. Nachtrag vom 08.10.2026: die Hypothese ist widerlegt

Abschnitt 4 hat eine Hypothese mit benannter Richtung hinterlassen: unsere
Regel verweigere genau die Einstiege, bei denen der Preis das Level berührt
und umkehrt, und nehme bevorzugt die, bei denen er durchläuft — also die
Verlierer.

Der Mechanismus dahinter war sogar besser begründet als er aussah: **unsere
Einstiegslevel sind frühere Preisextreme.** „Hoch genau gleich Limit" ist
damit kein Grenzfall, sondern der Normalfall „der Markt kam exakt zum alten
Hoch zurück und drehte". Ein Treffer auf den Tick ist bei einem Level, das
selbst ein gehandelter Preis war, plausibel häufig.

**Gemessen ist er das nicht.** 7 340 genommene Signale unter der
Hauptsignatur, Fenster 32 M15-Kerzen (8 h) auf Minutendaten:

| | n | Anteil |
|---|---|---|
| **durch** das Level → unsere Regel füllt | 7 221 | **98,4 %** |
| nie erreicht → beide Regeln verweigern | 73 | 1,0 % |
| **genau berührt** → nur unsere Regel verweigert | **39** | **0,5 %** |
| kein Fenster in den Daten | 7 | 0,1 % |

Die beiden Regeln sind sich auf **99,4 %** der Fälle einig. Selbst wenn alle
39 perfekte Gewinner wären, könnten sie an keiner Schlussfolgerung aus 7 221
Trades etwas ändern.

Der Grund ist einfach und im Nachhinein offensichtlich: innerhalb von acht
Stunden auf Minutendaten wird ein Level, das berührt wird, fast immer um
mindestens einen Tick überschritten. Ein exakter Halt auf den Tick ist
seltener, als die Herkunft des Levels vermuten lässt.

### Damit ist die Füllfrage für dieses System geschlossen

Drei Messungen, und sie greifen ineinander:

1. Unsere Regel füllt nur bei Durchhandeln → **0,6 % Falschfüllung** auf
   657 647 echten Orders.
2. Für unsere echten Einstiege unterscheiden sich Berührung und Durchhandeln
   auf **0,5 %** der Fälle.
3. Also ist das Füllmodell **in keiner gemessenen Grösse dieses Projekts eine
   wesentliche Fehlerquelle** — weder nach oben noch durch Auswahl.

Was offen bleibt, ist nicht die Regel, sondern die **Warteschlange** — und
zwar nur für einen Betrieb als Market Maker, der quotiert statt zu warten. Die
12,4 % Füllquote am Antritt aus Abschnitt 3 gilt für Quotes, nicht für
Einstiege, zu denen der Preis erst hinläuft: dort wird die Warteschlange beim
Durchhandeln aufgebraucht, und die Füllung ist belegt statt angenommen.

## 5. Grenzen

**Es sind die Orders anderer Leute**, alle 30 s abgetastet, also sind
langlebige überrepräsentiert — und langlebige sind eher die geduldigen, die
storniert werden. Das verzerrt die Falschfüll-Rate **nach oben**, die Zahl ist
also eine Obergrenze. Das stand vor dem Lauf fest.

**Andere Geometrie.** Die beobachteten Orders ruhen nahe am Mid und der Preis
schwingt um sie. Unsere Einstiege liegen auf einem Strukturlevel, zu dem der
Preis erst laufen muss. Der Mechanismus ist derselbe, die Population nicht.

**Ein Teil der 0,6 % ist Abtastung, nicht Modellfehler.** Das Zeitfenster
einer Order stammt aus 30-Sekunden-Aufnahmen; sie kann nach dem
Durchhandeln eingestellt worden sein.
