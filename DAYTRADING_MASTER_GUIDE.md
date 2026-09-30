# Daytrading Master Guide

> **Quellenstatus:** Diese Wissensbasis ist eine quellentreue Synthese der 13 Videos der Playlist „Trading by Loma“. Sie ist keine von der auswertenden KI entworfene Strategie. Jede operative Aussage wird einem Video zugeordnet. Wo ein Video einen Regelbestandteil nicht nennt, steht ausdrücklich „nicht spezifiziert“. Creator-Aussagen zu Trefferquote, Wahrscheinlichkeit, institutionellem Verhalten oder Profitabilität sind Behauptungen bzw. Erklärmodelle des jeweiligen Creators und keine durch das Video bewiesenen Tatsachen.

## Lese- und Belegsystem

- `V01` bis `V13` bezeichnen die Playlist-Videos in ihrer Reihenfolge; die vollständigen bibliografischen Angaben stehen in Kapitel 35 und in `video_sources.md`.
- **Regel** bedeutet hier: eine im Video konkret geäußerte Handlungsanweisung – nicht eine Garantie.
- **Invalidierung** beschreibt, wann das im Video dargestellte Setup nicht mehr gelten soll. Fehlt diese Angabe, wird nichts ergänzt.
- **Gegenbeispiel** ist nur dann genannt, wenn das Video selbst eines zeigt oder ausdrücklich eine Ausnahme formuliert.
- Begriffe wie „Institutionen“, „Liquidität als Treibstoff“ und „Preis will ein Ungleichgewicht füllen“ werden als Creator-Modelle wiedergegeben, nicht als empirisch bewiesene Kausalität.

---

# 1 Grundlagen

## 1.1 Was die Playlist unter Daytrading versteht

V01 definiert Daytrading als kurzfristige Spekulation, bei der Positionen am selben Handelstag eröffnet und geschlossen werden. Nach dieser Definition bleibt über Nacht keine Position offen. Gehandelt werden kleine Intraday-Bewegungen; Hebelprodukte werden häufig verwendet. Als Märkte bzw. Instrumente nennt V01 Aktien, Forex, Futures, Optionen, binäre Optionen und CFDs. Long bedeutet, auf steigende Kurse zu setzen; Short bedeutet, von fallenden Kursen profitieren zu wollen.

Der Hebel vergrößert nach V01 sowohl Gewinne als auch Verluste. Da teilweise mit geliehenem Kapital gearbeitet wird, können Verluste über das ursprünglich eingesetzte Kapital hinausgehen. Transaktionskosten wirken gerade bei hoher Handelsfrequenz kumulativ gegen das Ergebnis.

## 1.2 Markt als Ergebnis von Entscheidungen

V02 beschreibt Preisbewegung als Resultat der aggregierten Entscheidungen der Marktteilnehmer. Entscheidend sei nicht bloß die Anzahl von Käufern und Verkäufern, sondern die relative Größe ihres Kauf- bzw. Verkaufsvolumens. Als Kontextfaktoren nennt das Video:

- allgemeines Sentiment und bullisches bzw. bärisches Marktregime;
- regulatorische oder makroökonomische Ereignisse;
- große Marktteilnehmer („Whales“) und Market Maker;
- Gebühren, Ausführungsbedingungen und die Datenquelle des verwendeten Charts.

Diese Erklärung ist ein vereinfachtes Creator-Modell; das Video liefert keinen vollständigen mikrostrukturellen Nachweis.

## 1.3 Chart- und Kerzengrundlagen

Eine Candlestick-Kerze aggregiert für ihren Timeframe Open, High, Low und Close. Bei einer grünen Kerze liegt der Schlusskurs über dem Eröffnungskurs, bei einer roten darunter. Der Körper zeigt die Strecke zwischen Open und Close; Dochte zeigen die in der Periode erreichten Extremkurse. V02 empfiehlt, mehrere Zeitebenen – beispielhaft 5 Minuten, 15 Minuten, 30 Minuten, 1 Stunde, 4 Stunden und Tag – beobachten zu können. Diese Liste ist eine Empfehlung des Creators, keine in der Playlist validierte optimale Kombination.

## 1.4 Ergebnisqualität ist nicht Prozessqualität

V02 trennt den Ausgang eines einzelnen Trades von der Qualität der Entscheidung:

- Ein Verlust kann aus einem regelkonformen, gut vorbereiteten Trade entstehen.
- Ein Gewinn kann aus einem schlechten, zufälligen oder FOMO-getriebenen Trade entstehen.
- Deshalb sollen Regeln, Risiko, Entry-Grund und Exit vorab dokumentiert und über eine Serie von Trades ausgewertet werden.

## 1.5 Demo- und Lernphase

V01 empfiehlt vor echtem Kapitaleinsatz ein Demokonto. V02 konkretisiert dies mit einer persönlichen Empfehlung von mindestens 100 Paper-Trades, bevor reales Geld eingesetzt wird. Diese Zahl ist die Regel des Creators; die Playlist liefert keine statistische Herleitung für genau 100 Trades.

## Quellen dieses Abschnitts

- **In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)** — Finanzfluss — https://www.youtube.com/watch?v=W9rc0RQvf0s
- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78

---

# 2 Marktstruktur

## 2.1 Swing-Logik

Mehrere Playlist-Videos verwenden dieselbe Basissprache:

- Aufwärtstrend: Folge höherer Hochs und höherer Tiefs (`HH`/`HL`).
- Abwärtstrend: Folge tieferer Tiefs und tieferer Hochs (`LL`/`LH`).
- Konsolidierung: keine klare fortlaufende Struktur; bullische und bärische Signale können abwechselnd scheitern.

V05 nutzt diese Struktur als Filter für FVGs: im Aufwärtstrend nur bullische FVGs, im Abwärtstrend nur bärische. V06 verlangt bei einem möglichen bullischen Trendlinienausbruch nicht nur einen ersten Bruch, sondern optional einen zweiten Strukturbruch: erst ein neues höheres Hoch, danach ein erneuter Bruch dieses Hochs. V10 ordnet BOS und CHoCH explizit über Buy-Side- und Sell-Side-Liquidität ein.

## 2.2 Swingpunkte als Liquiditätsniveaus

Nach V10 entstehen an einem Swing High Buy-Side Liquidity und an einem Swing Low Sell-Side Liquidity. Welches dieser Niveaus zuletzt durchlaufen wurde, bestimmt im Modell des Videos den aktuellen Orderflow:

- Durchlaufene Buy-Side Liquidity → bullischer Orderflow.
- Durchlaufene Sell-Side Liquidity → bärischer Orderflow.

Der nächste Bruch in Trendrichtung ist der BOS-Kandidat; der Bruch der Gegenseite ist zunächst ein CHoCH-Kandidat. Ein CHoCH allein reicht V10 noch nicht für einen Bias-Wechsel, weil es sich um einen Sweep handeln könnte. Das Video wartet auf einen weiteren BOS in der neuen Richtung.

## 2.3 Konsolidierung erkennen

V05 beschreibt eine operative Warnung: Wird ein bullisches FVG nicht respektiert und anschließend auch ein neu gebildetes bärisches FVG nicht respektiert, soll dies als Hinweis auf Konsolidierung gelten. Wer nur Trendphasen handeln will, wartet nach dieser Regel auf zwei neu gebildete und respektierte FVGs, bevor ein kurzfristiger Bias festgelegt wird.

## Regelkarte: Strukturgefilterter Bias

| Feld | Aus dem Video extrahierte Aussage |
|---|---|
| Konzept | Trades sollen der bestehenden Folge aus HH/HL bzw. LL/LH und dem aktuellen Orderflow folgen. |
| Erkennung | Swingpunkte markieren; prüfen, welche externe Liquiditätsseite durchlaufen wurde. |
| Timeframe | V10 demonstriert 4H, 15M und Weekly; Regel wird nicht auf diese Kombination begrenzt. |
| Marktumfeld | Klarer Trend; bei alternierend scheiternden FVGs Konsolidierungswarnung. |
| Voraussetzungen | Eindeutige relevante Swing Highs und Swing Lows. |
| Entry | Nicht allein durch die Struktur spezifiziert; Entries folgen in den Setup-Kapiteln über FVG, Zone oder Retest. |
| Bestätigung | BOS in Trendrichtung; für Reversal nach CHoCH zusätzlich BOS in neuer Richtung. |
| Invalidierung | Bruch der Gegenseite/CHoCH; endgültiger Bias-Wechsel erst nach nachfolgendem BOS. |
| Stop Loss | Nicht als allgemeine Marktstrukturregel spezifiziert. |
| Take Profit | Gegenseitige externe Liquidität bzw. vorheriges Hoch/Tief in den jeweiligen Setups. |
| Häufige Fehler | CHoCH sofort als voll bestätigte Umkehr behandeln; Konsolidierung als Trend handeln. |
| Gegenbeispiel | V10 zeigt, dass ein scheinbarer CHoCH nur ein Liquidity Sweep sein kann. |
| Unterstützende Videos | V05, V06, V10, V12. |

## Quellen dieses Abschnitts

- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE

---

# 3 Multi-Timeframe-Analyse

## 3.1 Top-down statt isolierter Entry-Timeframe

V04 empfiehlt für Trades auf 1M oder 5M, die bedeutenden Support-/Resistance-Zonen zuerst auf 1H einzuzeichnen. Das Video begründet dies mit weniger Rauschen und weniger falschen Brüchen auf höheren Zeitebenen. Anschließend wird auf dem niedrigeren Timeframe eine Bestätigung gesucht; eine Higher-Timeframe-Zone wird nicht blind per Limitorder gehandelt.

V10 demonstriert ein vollständigeres Top-down-Modell:

1. Auf 4H wird der Orderflow über BOS bestimmt.
2. Innerhalb des 4H-Swings wird ein passendes FVG gesucht.
3. Auf 15M wird zunächst der lokale Orderflow gelesen.
4. Für einen Long in bullischem 4H-Kontext wartet das Video auf 15M-Sweep, Missachtung des bärischen FVG, CHoCH, bullischen BOS und das erste danach entstehende bullische FVG.
5. Das Ziel liegt an der 4H-Buy-Side-Liquidität.
6. Soll länger gehalten werden, wird zusätzlich der Weekly-Kontext geprüft. Im Beispiel liegt der 4H-Long in einem übergeordneten bearishen Weekly-FVG; deshalb erwartet der Creator später wieder eine Reaktion zugunsten der Weekly-Struktur.

V05 nutzt 4H → 15M zur Entry-Verfeinerung: Ein großes 4H-FVG liefert den Bereich, ein darin liegendes 15M-FVG den engeren Entry-Bereich. V12 nutzt 1H → 15M: erst „wahre“ Higher-Timeframe-Zone, dann LTF-BOS und Rücklauf in ein LTF-Imbalance.

## Regelkarte: 4H-/15M-Liquiditätsmodell aus V10

| Feld | Regel |
|---|---|
| Konzept | LTF-Reversal innerhalb eines HTF-FVG in Richtung des HTF-Orderflows. |
| Erkennung | 4H-BOS, passendes 4H-FVG; auf 15M lokaler Sweep und Strukturwechsel. |
| Timeframe | Beispiel: 4H Kontext, 15M Entry, Weekly übergeordneter Kontext. |
| Marktumfeld | HTF-Trend mit Retracement in internes Liquiditätsgebiet. |
| Voraussetzungen | 4H-FVG liegt im vorherigen Impuls; Preis erreicht es. |
| Entry | Erstes bullisches FVG nach abgeschlossenem 15M-Reversal („Silver Bullet“ im Sprachgebrauch des Videos). |
| Bestätigung | Sweep → gegnerisches FVG wird missachtet → CHoCH → BOS in HTF-Richtung. |
| Invalidierung | Im Video nicht als fixer Preislevel formuliert; fehlender BOS bedeutet, dass die Umkehr nicht vollständig bestätigt ist. |
| Stop Loss | Für dieses Beispiel nicht numerisch bzw. positionsbezogen spezifiziert. |
| Take Profit | 4H Buy-Side Liquidity; für längeres Halten zusätzlich größere Struktur analysieren. |
| Häufige Fehler | Blind im 4H-FVG einsteigen; Weekly-Struktur ignorieren. |
| Gegenbeispiel | Kurzfristig bullisches 4H-Setup kann innerhalb eines bearishen Weekly-FVG liegen. |

## Quellen dieses Abschnitts

- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE

---

# 4 Candlesticks

## 4.1 Muster aus V03

| Muster | Erkennung laut Video | Kontext/Bestätigung | Entry/Invalidierung/Exit |
|---|---|---|---|
| Bullish Engulfing | Neue Kerze öffnet am/unter vorherigem Close und schließt über vorherigem Open; bearish spiegelverkehrt. | An etabliertem Support/Resistance als Bestätigung, nicht allein. | Konkreter SL/TP nicht spezifiziert. |
| Momentum Candle | Eine große Kerze, ungefähr zwei- bis dreimal so groß wie vorherige Kerzen. | Besonders beim Ausbruch aus seitwärts/choppy Markt; Fortsetzungsindiz. | Entry nach bestätigtem Breakout; V08 präzisiert Varianten. |
| Multiple-Wick Pattern | Mindestens drei Kerzen mit Dochten in dieselbe Richtung. | Lange untere Dochte an Support bullisch; lange obere Dochte an Resistance bearish. Creator behauptet: mehr beteiligte Kerzen verstärken das Signal. | Konkreter SL/TP nicht spezifiziert. |
| Doji | Sehr kleiner Körper, Dochte auf beiden Seiten; Unentschlossenheit. Varianten: normal, long-legged, dragonfly, gravestone. | Mögliches Reversal; V03 wartet zusätzlich auf zwei Kerzen gleicher neuer Richtung. | Entry erst nach diesen zwei Bestätigungskerzen; SL/TP nicht spezifiziert. |
| Hammer | Körper mit langem unteren Docht; Verkäufer wurden zurückgewiesen bzw. Käufer absorbierten den Druck. | Bullishes Reversal-Signal in passendem Kontext. | Nicht allein handeln; SL/TP nicht spezifiziert. |
| Shooting Star | Gegenstück zum Hammer mit langem oberen Docht. | Bearishes Reversal-Signal in passendem Kontext. | Nicht allein handeln; SL/TP nicht spezifiziert. |
| Tweezer Bottom/Top | Bottom: rote, dann grüne Kerze mit ähnlichen Tiefdochten an Support. Top: grün, dann rot mit ähnlichen Hochdochten an Resistance. | Rejection an einem Level. | Konkreter SL/TP nicht spezifiziert. |
| Marubozu | Große Kerze ohne bzw. nahezu ohne Dochte. | Fortsetzung in Trendrichtung. | Konkreter SL/TP nicht spezifiziert. |

## 4.2 Candles im Breakout-Modell aus V08

V08 nennt zwei akzeptierte Momentum-Formen:

- eine einzelne große Kerze, deren Körper mehrheitlich jenseits des Ausbruchsniveaus liegt;
- drei mittelgroße Kerzen in derselben Richtung außerhalb des Niveaus.

Nur ein Docht oder eine kleine Körperspitze über dem Level zählt nicht. Eine kleine Ausbruchskerze gefolgt von einer roten Kerze wird im Long-Beispiel verworfen. Nach der dritten gleichgerichteten Kerze erfolgt der Entry am Schlusskurs.

## 4.3 Grundsatz der Playlist

V03 warnt ausdrücklich davor, Candlestick-Muster allein zu handeln. Sie sind Hinweise, keine Entscheidungsgarantie. Das Video kombiniert sie mit Support/Resistance, weiteren Indikatoren oder einer übergeordneten Strategie. V06 nutzt beispielsweise ein bearish Engulfing nach einem schwachen Trendlinien-Fakeout und wartet zusätzlich auf den Bruch des Swing Lows.

## Quellen dieses Abschnitts

- **The ONLY Candlestick Pattern Guide You'll EVER NEED** — TradingLab — https://www.youtube.com/watch?v=tW13N4Hll88
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8

---

# 5 Support & Resistance

## 5.1 Zeichnen und Pflegen

V04 formuliert folgende Arbeitsweise:

1. Bei 1M-/5M-Trading bedeutende Levels auf 1H markieren.
2. Anfänger können vorübergehend auf den Linienchart wechseln, um markante Wendebereiche leichter zu sehen, danach zurück auf Candles.
3. Support und Resistance als Bereiche/Zonen behandeln, nicht als millimetergenaue Linien.
4. Levels täglich aktualisieren; vom Markt wiederholt ignorierte Levels löschen und neue relevante Wendepunkte ergänzen.
5. Zu viele LTF-Linien vermeiden, weil sie Chart-Clutter und Zögern erzeugen.

## 5.2 Entry-Regel

Ein HTF-Level allein ist nach V04 kein Entry. Im gezeigten Short-Beispiel kommen Resistance, steigende Trendlinie und Pivot-Bereich zusammen. Der Trade wird erst erwogen, nachdem Trendlinie und Pivot brechen. Ein weiteres Beispiel kombiniert Level, VWAP, Moving Average und Pivot. Die konkrete Behauptung des Videos lautet, dass mehrere unabhängige Überschneidungen den Bereich stärker machen; ein statistischer Nachweis wird nicht geliefert.

## Regelkarte: HTF-S/R mit LTF-Bestätigung

| Feld | Regel |
|---|---|
| Konzept | Große Zone auf HTF, Auslöser auf LTF. |
| Erkennung | Mehrfach erkennbare Wendebereiche; als Zone statt exakter Linie. |
| Timeframe | 1H-Level für 1M-/5M-Trades im Beispiel. |
| Marktumfeld | Trend- oder Range-Kontext; Kontext muss separat gelesen werden. |
| Voraussetzungen | Aktuelles, vom Markt noch respektiertes HTF-Level. |
| Entry | Nach Bruch zusätzlicher Bestätigung wie Trendlinie/Pivot/Key Area. |
| Bestätigung | Confluence aus Level und weiteren im Video genannten Werkzeugen. |
| Invalidierung | Level wird klar ignoriert; bei falschem Break Rückkehr in die Zone. |
| Stop Loss | Nicht allgemein spezifiziert. |
| Take Profit | Bei Fakeout-Beispiel nächster Support; sonst nicht allgemein spezifiziert. |
| Häufige Fehler | Blindes Limit am Level; zu viele Linien; exakte Linie statt Zone. |
| Gegenbeispiel | Kurzer Bruch über Resistance mit sofortiger Rejection kann Fakeout statt Breakout sein. |

## Quellen dieses Abschnitts

- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **The ONLY Candlestick Pattern Guide You'll EVER NEED** — TradingLab — https://www.youtube.com/watch?v=tW13N4Hll88

---

# 6 Supply & Demand

## 6.1 Definition und Zonenzeichnung nach V09

- **Supply:** Bereich, von dem aggressives Verkaufen ausging.
- **Demand:** Bereich, von dem aggressives Kaufen ausging.
- Eine bloße Folge kleiner Kerzen reicht dem Creator nicht; der Abgang muss sichtbar aggressiv sein.
- Demand-Zone: die letzte rote Kerze vor dem aggressiven Anstieg, markiert von Low bis High.
- Supply-Zone: die letzte grüne Kerze vor dem aggressiven Abverkauf, ebenfalls Low bis High.

Das Video sagt ausdrücklich, dass es mehrere Zeichnungsmethoden gibt und dies die persönliche Methode des Creators ist.

## 6.2 Validierung

Eine Zone gilt in V09 nur dann als validiert, wenn der aggressive Move eine relevante Struktur bricht. Aggressiver Abgang ohne BOS wird nicht gehandelt. Zwei zusätzliche Qualitätsfilter:

1. Die Rückkehr soll langsam und stetig erfolgen. Eine aggressive, scharfe Bewegung zurück in die Zone ist ein No-Trade-Signal des Videos.
2. Am Anfang des impulsiven Moves soll ein FVG liegen und mit der ersten Kerze der Zone verbunden sein. Ohne FVG könne die Zone laut Creator noch funktionieren, er bewertet sie aber als schwächer.

## Regelkarte: Supply-/Demand-Retest

| Feld | Demand-Variante | Supply-Variante |
|---|---|---|
| Erkennung | Letzte rote Kerze vor aggressivem Anstieg. | Letzte grüne Kerze vor aggressivem Abverkauf. |
| Timeframe | Nicht eingeschränkt. | Nicht eingeschränkt. |
| Marktumfeld | Impulsiver Kaufmove mit BOS. | Impulsiver Verkaufsmove mit BOS. |
| Voraussetzungen | BOS; bevorzugt FVG am Ursprung; langsamer Rücklauf. | BOS; bevorzugt FVG am Ursprung; langsamer Rücklauf. |
| Entry | Bei Rückkehr in Demand-Zone. | Bei Rückkehr in Supply-Zone. |
| Bestätigung | Qualität entsteht laut Video durch aggressiven Abgang, BOS, FVG und langsame Rückkehr. | Spiegelverkehrt. |
| Invalidierung | Aggressiver Rücklauf; Zone ohne BOS wird nicht validiert. | Spiegelverkehrt. |
| Stop Loss | Knapp unter der Zone. | Knapp über der Zone. |
| Take Profit | Hoch des impulsiven Moves. | Tief des impulsiven Moves. |
| Häufige Fehler | Jede Aufwärtsbewegung als Demand markieren; Zone ohne BOS; scharfe Rückkehr kaufen. | Spiegelverkehrt. |
| Gegenbeispiel | Langsamer Abgang ohne echte Aggression gilt nicht als hochwertige Zone. | Spiegelverkehrt. |

## Quellen dieses Abschnitts

- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI

---

# 7 Trendlines

## 7.1 Definition und Konstruktion

V06 definiert eine Trendlinie als diagonalen Support bzw. Widerstand durch eine Folge von Swing Lows oder Swing Highs in einem Trendmarkt.

- Mindestens zwei signifikante Ankerpunkte.
- Offensichtliche Hochs/Tiefs mit sauberer Wegbewegung verwenden.
- Der Creator bevorzugt Dochte, akzeptiert aber in manchen Fällen Bodies.
- Entscheidend ist Konsistenz: nicht zwischen Docht und Body wechseln, um die eigene Erwartung passend zu machen.
- Trendlinie nie allein handeln; genannte Confluences sind horizontale Key Levels und Fibonacci-Level.

## 7.2 Fakeout versus echter Break

V06 trennt nach sichtbarer Energie:

- Kleine Kerzen, die nur leicht jenseits der Linie abweichen, deuten im Modell eher auf Fakeout.
- Große, impulsive Kerzen durch die Linie plus Folgekerzen in derselben Richtung deuten eher auf echten Breakout.
- Zusätzliche Bestätigung: zweiter BOS. Für bullisch zuerst Bruch eines Swing Highs zu neuem HH, danach erneuter Bruch dieses HH; Entry am Retest des neu geschaffenen Levels.

## 7.3 Trendlinien als Liquidität

V06 zeigt außerdem ein Modell, in dem Stops von Trendlinien-Shorts oberhalb der fallenden Linie liegen. In einem übergeordnet bullischen Trend wartet der Creator auf die Bewegung durch diese „Trendline Liquidity“ und einen Rücklauf in ein bullisches FVG. Stop unter dem FVG, Ziele an höheren Levels. Dies ist ein Interpretationsmodell des Videos, kein unabhängig belegter Orderbuchnachweis.

## Quellen dieses Abschnitts

- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78

---

# 8 Chart Patterns

V07 kündigt 16 bullische/bärische Darstellungen an. Das verfügbare Transkript benennt nicht jede Darstellung sauber; die Wissensbasis übernimmt deshalb nur eindeutig benannte Muster.

| Muster | Erkennung laut V07 | Entry | Stop | Ziel / Zusatzregel |
|---|---|---|---|---|
| Bull Flag | Starker bullischer Impuls, danach kleiner abwärts gerichteter Zickzack-Kanal. | Break der oberen Kanalgrenze; Video erwähnt einen Entry ungefähr zur Hälfte des Ausbruchskanals. | Im gezeigten Schema unter/innerhalb des Kanals; exakte Methode sprachlich nicht eindeutig. | Links liegendes Hoch/Preislevel; Fibonacci-Retracement des Pullbacks beobachten (.382 bei starkem Momentum, teils .5/.618 laut Creator). |
| Bear Flag | Starker Abverkauf, aufwärts gerichteter kleiner Kanal. | Break der unteren Kanalgrenze. | Oberhalb/innerhalb des Kanals im Schema. | Links liegendes Tief/Level. |
| Cup and Handle | Abgerundeter Boden, kleinere zweite Rundung/Handle ungefähr in der halben Range. | Breakout aus dem Handle. | Unter dem Handle im Schema. | Vorheriger Widerstandsbereich links. Creator sagt, er nutzt es selten. |
| Inverse Cup and Handle | Spiegelbild. | Bearisher Break. | Oberhalb des Handles im Schema. | Linkes Preislevel. |
| Enge Konsolidierung (im Transkript unbenannt) | Schneller Move in eine sehr enge Range, keine Zwischenbrüche. | Break aus der Range. | Jenseits der Range. | Vorheriges Hoch/Tief links; wenn nicht mehr als 2:1 möglich, laut Video auslassen, da ein größerer Move erwartet wird. |
| Bull/Bear Pennant | Impuls, anschließend konvergierende Begrenzungen; bullisch mit steigenden Tiefs. | Break nahe Ende des Keils. | Jenseits des Pennants. | Linkes Preislevel. |
| Double Top/Bottom | Zwei ungefähr gleiche Hochs bzw. Tiefs. | Das Video koppelt es an RSI-Divergenz, spezifiziert den genauen Entry im Transkript aber nicht vollständig. | Nicht spezifiziert. | Double Top: RSI niedrigeres Hoch; Double Bottom: RSI höheres Tief. |
| Head and Shoulders / inverse | Drei Spitzen, mittlere höher bzw. tiefer; Neckline kann geneigt sein. | Bruch der Neckline. | Nicht eindeutig sprachlich spezifiziert. | Nächstes linkes Rejection-Level. Video ordnet das Muster 1H, 4H oder Daily zu, nicht Scalping. |
| Falling/Rising Wedge | Konvergierender, abwärts- bzw. aufwärtsgerichteter Keil. | Break aus dem Keil. | Falling Wedge darunter; Rising Wedge darüber. | Linke Preislevel. |
| Ascending/Descending Triangle | Horizontale Verkäufer-/Käuferseite plus ansteigende Tiefs bzw. fallende Hochs. | Break der horizontalen Seite. | Nicht in diesem Transkript spezifiziert. | Creator erklärt es als nachlassende Gegenpartei. |
| Symmetric Triangle | Konvergierende Hochs und Tiefs; Richtung zunächst ausgeglichen. | Creator wartet auf dramatischen Break und scalp-artigen Entry. | Nicht spezifiziert. | Vorherige Bewegungsrichtung links dient ihm als Bias, dennoch wartet er auf den Break. |

## Wichtige Einschränkungen aus V07

- Muster sind in realen Charts nicht geometrisch perfekt.
- Take-Profit-Bereiche werden wiederholt durch „nach links schauen“ bestimmt, also frühere Rejections/Hochs/Tiefs.
- Die Aussage, ein bestimmtes Muster „normalerweise“ zu einem Move führe, ist eine Creator-Aussage; im Video wird keine Out-of-sample-Statistik gezeigt.

## Quellen dieses Abschnitts

- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc

---

# 9 Breakouts

## 9.1 Struktur des Breakout-Setups aus V08

Ein Breakout-Bereich besteht aus Support und Resistance mit mehreren sichtbaren Rejections. Wedge, Flag, Rectangle, Triangle und Pennant sind nach V08 nur unterschiedliche Formen desselben Kerns: Preis konsolidiert zwischen zwei wichtigen Begrenzungen und verlässt sie später. Der Creator rät, nicht auf ein perfektes Lehrbuchbild zu warten, sondern die tragenden Levels zu erkennen. Mehr valide Berührungspunkte seien besser.

## 9.2 Zwei Entry-Varianten in der Playlist

**Momentum-Close (V08):** Entry am Close einer großen Momentum-Kerze, deren Körper überwiegend außerhalb liegt, oder nach drei mittelgroßen gleichgerichteten Kerzen. Stop knapp hinter dem gebrochenen Level.

**Bestätigter Break-Retest (V06):** Impulsiver Trendlinienbruch, dann weiterer Strukturbruch; Entry am Retest des neu geschaffenen Support-/Resistance-Levels bzw. eines dabei entstandenen FVG.

Diese Varianten widersprechen sich nicht zwingend, sind aber unterschiedliche Timing-Modelle: V08 priorisiert Teilnahme ohne verpassten Direktmove; V06 priorisiert zusätzliche Strukturinformation. Die Playlist beweist nicht, welches Modell profitabler ist.

## 9.3 Zwei-Stufen-Exit aus V08

1. Initialer TP bei 1,5R.
2. Dort die Hälfte der Position schließen.
3. Stop der Restposition auf das frühere TP-Level anheben.
4. Chandelier Stop in TradingView mit ATR-Multiplikator 2 verwenden.
5. Restposition schließen, wenn der Indikator die Farbe wechselt.

Dies ist eine konkrete Creator-Regel. Das Video zeigt Beispiele, aber keine vollständige Backtest-Verteilung.

## Quellen dieses Abschnitts

- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc

---

# 10 False Breakouts

## 10.1 Erkennung

Die Playlist nennt mehrere Hinweise auf einen falschen Break:

- nur der Docht oder ein kleiner Teil des Körpers überschreitet das Level (V08);
- kleine, energiearme Kerzen statt impulsiver Bewegung (V06);
- keine Folgekerzen in Ausbruchsrichtung (V06/V08);
- Break über Swing High, aber kein Close darüber (V05/V10: Liquidity Sweep);
- nach kurzem Break Rückkehr durch die Zone bzw. unter das gebrochene Level (V04/V08);
- ein vorhandenes FVG auf der Trendseite wird vollständig missachtet und danach Struktur in Gegenrichtung gebrochen (V10).

## 10.2 Handlungsmodelle

**V08:** Nicht beim ersten Durchstich einsteigen. Auf eine große Body-Kerze oder drei gleichgerichtete Kerzen warten. Stop hinter dem Level schützt für den Fall, dass der bestätigte Break dennoch scheitert.

**V06:** Schwachen Break als möglichen Fakeout behandeln; nach Gegenreaktion, Engulfing und Bruch des gegengerichteten Swingpunkts auf Retracement in ein neu entstandenes FVG einsteigen. Im bearishen Beispiel liegt der Stop über dem Hoch, die Ziele an tieferen Levels.

**V10:** Reaktion am externen Liquiditätslevel allein nicht handeln. Nach Sweep auf Missachtung des alten FVG, CHoCH, neues FVG in Gegenrichtung und BOS warten.

## Regelkarte: Bestätigter Fakeout-Reversal aus V10

| Feld | Regel |
|---|---|
| Konzept | Externes Liquiditätslevel wird angegriffen, aber Orderflow kippt statt fortzusetzen. |
| Erkennung | Fehlender Close über Level oder späteres Zurückfallen und Missachtung des Trend-FVG. |
| Timeframe | V10 demonstriert MTF; keine universelle feste Ebene. |
| Marktumfeld | Angriff auf vorheriges Swing High/Low. |
| Voraussetzungen | Identifizierte ERL und vorhandenes IRL/FVG. |
| Entry | Im ersten neuen FVG nach bestätigtem Strukturwechsel. |
| Bestätigung | Sweep/Failure → altes FVG missachtet → CHoCH → neues Gegen-FVG → BOS. |
| Invalidierung | Fortsetzung/Run mit neuem trendgerichtetem FVG während oder nach dem Break. |
| Stop Loss | Nicht als allgemeine fixe Position angegeben. |
| Take Profit | Nächste externe Liquidität der neuen Richtung. |
| Häufige Fehler | Allein wegen eines Dochts gegen den Trend handeln. |
| Gegenbeispiel | Close über Level schließt Sweep nicht aus; erst spätere Struktur entscheidet. |

## Quellen dieses Abschnitts

- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8

---

# 11 Liquidity

## 11.1 Zwei Formen nach V10

- **External Range Liquidity (ERL):** vorheriges Swing High oder Swing Low; oben Buy-Side, unten Sell-Side.
- **Internal Range Liquidity (IRL):** im Modell von V10 Fair Value Gaps innerhalb des Swings.

Der Creator beschreibt IRL als „fuel“, mit dem Preis ERL angreift. Praktisch übersetzt das Video dies so: In einem bullischen Swing wird ein bullisches FVG als möglicher Support für den nächsten Angriff auf Buy-Side Liquidity gesucht; im bearishen Swing ein bärisches FVG als Resistance vor dem Angriff auf Sell-Side Liquidity.

## 11.2 Inducement nach V12

V12 nennt eine scheinbar attraktive, aber schwache Zone „Inducement Zone“. Liegt darunter ein ungetestetes Imbalance und eine andere Zone, erwartet das Video, dass Preis die erste Zone bricht, dortige Stops/Breakout-Orders aufnimmt und zur „true zone“ läuft. Für die Auswahl der echten Zone genügt laut V12 nicht, einfach die tiefste Zone zu nehmen: Entscheidend sei, welche Zone den relevanten Strukturbruch tatsächlich verursachte. Ein bloßer Wick über ein Hoch zählt im Beispiel nicht als starker Bruch.

## 11.3 Nicht nachgewiesene Kausalität

V11 und V12 erklären Bewegungen mit institutionellen Orders und benötigter Liquidität. Diese Aussagen werden hier als SMC-Erklärmodell dokumentiert. Die Videos zeigen Charts, aber keine direkten Daten institutioneller Einzelorders; deshalb darf „Institutionen waren dort aktiv“ nicht als bewiesener Fakt gelesen werden.

## Quellen dieses Abschnitts

- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8

---

# 12 Liquidity Sweeps

## 12.1 Sweep versus Run

V10 definiert zwei mögliche Reaktionen am externen Liquiditätslevel:

- **Liquidity Run:** Fortsetzung durch das Level.
- **Liquidity Sweep:** Angriff auf das Level mit anschließender Umkehr.

Ein Close oberhalb eines Swing Highs ist zunächst nur ein Breakout, noch kein bestätigter Run. Für einen bullishen Run verlangt V10 ein bullisches FVG, das während des Breaks, überlappend mit dem Break oder danach oberhalb entsteht. Ein FVG, das bereits vor dem Levelbruch entstand, validiert den Run nach dieser Regel nicht.

Ein klarer Sweep liegt im einfachsten Fall vor, wenn Preis das Hoch attackiert, aber nicht darüber schließt. Schließt die Kerze doch darüber, kann es laut V10 trotzdem ein Sweep werden, wenn anschließend das letzte bullische FVG missachtet, das vorherige Swing Low gebrochen (CHoCH), ein bärisches FVG gebildet und durch einen weiteren bearishen BOS die neue Richtung bestätigt wird.

## 12.2 Orderblock-Sweep-Regel aus V11

V11 verlangt für einen validen Orderblock, dass die letzte Gegenkerze vor dem Richtungswechsel Liquidität links von ihr sweept. Für einen bearishen Orderblock soll sie also die Bewegung abschließen, Liquidität oberhalb nehmen und anschließend einen impulsiven, FVG-erzeugenden Richtungswechsel einleiten. Der Sweep ist hier nur das erste von drei Kriterien; FVG und CHoCH müssen folgen.

## Quellen dieses Abschnitts

- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4

---

# 13 BOS

## 13.1 Definitionen in der Playlist

V10 definiert Break of Structure als Bruch des Liquiditätsniveaus, der die Fortsetzung des aktuellen Trends bestätigt:

- Bullischer Orderflow: Bruch der Buy-Side Liquidity / des vorherigen Swing Highs.
- Bearisher Orderflow: Bruch der Sell-Side Liquidity / des vorherigen Swing Lows.

V09 und V13 nutzen eine einfachere Version: Ein Supply-/Demand-Bereich bzw. FVG gilt nur dann als hochwertig, wenn der verursachende Impuls eine vorherige Struktur bricht. V12 verfeinert dies: Ein bloßer Wick knapp über ein Hoch kann als unzureichend gelten; die Zone, deren Move den tatsächlichen relevanten Bruch verursachte, erhält Priorität.

## 13.2 BOS ist kontextabhängig

Nicht jeder sichtbare Mikrobruch ist automatisch der relevante BOS. V11 wählt für CHoCH/BOS den Punkt, von dem der eigentliche Impuls zum Extrem ausging. V09 erwähnt, dass nur „main structures“ markiert werden sollen, erklärt im gesprochenen Inhalt aber keine vollständig objektive Swing-Selektion. Diese verbleibende Diskretion muss dokumentiert werden; sie darf nicht durch eine erfundene Pivot-Regel ersetzt werden.

## Regelkarte: BOS als Zonenfilter

| Feld | Regel |
|---|---|
| Konzept | Nur eine Zone/FVG handeln, deren Impuls relevante Struktur brach. |
| Erkennung | Close/Bewegung durch vorheriges relevantes Hoch oder Tief; V12 verwirft einen bloßen knappen Wick im Beispiel. |
| Timeframe | Jeder betrachtete Struktur-Timeframe; V12 demonstriert 1H und 15M. |
| Marktumfeld | Trendfortsetzung oder Bestätigung einer neuen Richtung nach CHoCH. |
| Voraussetzungen | Relevanter Swingpunkt muss vorab bestimmt sein. |
| Entry | Nicht am BOS selbst zwingend; meist Rücklauf in Ursprungszone/FVG. |
| Bestätigung | BOS in gewünschter Richtung. |
| Invalidierung | Kein echter Strukturbruch; nur Wick/zu schwacher Bruch im gezeigten V12-Beispiel. |
| Stop Loss | Setupabhängig jenseits Zone/FVG/Swing. |
| Take Profit | Vorheriges Hoch/Tief oder nächste externe Liquidität. |
| Häufige Fehler | Beliebigen kleinen Swing als Hauptstruktur behandeln. |
| Gegenbeispiel | Aggressiver Move ohne BOS validiert die Supply-/Demand-Zone in V09 nicht. |

## Quellen dieses Abschnitts

- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 14 CHoCH / MSS

## 14.1 CHoCH nach V10

Change of Character ist das erste Signal, dass der Orderflow wechseln könnte. In einem validierten Aufwärtstrend ist das relevante Gegenniveau die Sell-Side Liquidity. Wird sie gebrochen und ein tieferes Tief erzeugt, entsteht ein bearish CHoCH. Umgekehrt entsteht ein bullish CHoCH beim Bruch der Buy-Side Liquidity in zuvor bearishen Strukturen.

V10 warnt: CHoCH bedeutet „könnte sich ändern“, nicht „hat sich vollständig geändert“. Der Bruch kann nur ein Sweep sein. Der Creator wartet deshalb auf den nächsten BOS in der neuen Richtung.

## 14.2 Orderblock-Validierung nach V11

V11 verlangt, dass der Impuls vom potenziellen Orderblock die relevante Struktur bricht und damit einen Richtungswechsel zeigt. Alle drei Bedingungen – Liquidity Sweep, impulsive Wegbewegung mit FVG und CHoCH – müssen vor einer Rückkehr in den Block erfüllt sein. Wird der Block vorher mitigiert, verwirft V11 ihn.

## 14.3 MSS

Der Begriff **Market Structure Shift (MSS)** wird in den 13 ausgewerteten Playlist-Transkripten nicht als eigenständiges, objektiv abgegrenztes Modell definiert. V12 spricht von einem „structural shift“ und setzt ihn im Beispiel mit einem LTF-BOS von Abwärts- zu Aufwärtsstruktur gleich. Eine zusätzliche MSS-Regel – etwa eine zwingende Displacement-Kerze oder spezielle Swing-Definition – wäre daher eine externe Ergänzung und wird nicht erfunden.

## Quellen dieses Abschnitts

- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE

---

# 15 Order Blocks

## 15.1 Definition nach V11

Ein Orderblock ist in der vereinfachten Definition von V11 die letzte Kerze vor einem starken Richtungswechsel. Der Creator akzeptiert diese Kerze aber erst als validen Block, wenn drei Bedingungen erfüllt sind:

1. Die Kerze sweept Liquidität links von sich.
2. Preis bewegt sich impulsiv weg und bildet ein FVG.
3. Die Bewegung erzeugt einen CHoCH auf der betrachteten Strukturdimension.

Zusätzlich muss der Block bis zum CHoCH unmitigiert bleiben. Erfolgt die Rückkehr vorher, sieht der Creator keinen Grund, später denselben Block erneut zu handeln.

## 15.2 Entry-Variante nach V11

V11 betont, dass der Markt nicht exakt die Blockkante treffen muss. Eine Mitigation bis etwa 50 % kann vorkommen; manchmal reagiert Preis bereits im vorgelagerten FVG. Der Creator sucht deshalb persönlich den Entry schon im FVG und deckt mit dem Stop-/Risikobereich den gesamten Orderblock ab. Ein konkretes Gewinnziel oder eine fixe R-Multiple-Regel nennt dieses Video nicht.

## 15.3 Inducement-Auswahl nach V12

V12 behandelt mehrere potenzielle Zonen:

1. Zonen mit noch tiefer liegendem, ungetestetem Imbalance werden als mögliche Inducement-Zonen verworfen.
2. Nicht automatisch die tiefste Zone wählen.
3. Prüfen, welche Zone das relevante Hoch tatsächlich brach.
4. Warten, bis Preis eine Inducement-Zone bricht und die „true zone“ erreicht.
5. Vom 1H-Chart auf 15M wechseln.
6. Auf bullishen Strukturwechsel/BOS warten.
7. Entry beim Rücklauf in ein 15M-Imbalance.
8. Stop unter dem Higher-Timeframe-Tief; Ziel am vorherigen Hoch.

## Regelkarte: Noc-Trading-Orderblock

| Feld | Regel |
|---|---|
| Konzept | Letzte Gegenkerze vor validiertem Richtungswechsel. |
| Erkennung | Sweep links + impulsive Wegbewegung/FVG + CHoCH. |
| Timeframe | Laut V11 auf jedem Timeframe; keine bevorzugte Ebene genannt. |
| Marktumfeld | Richtungswechsel an Liquidität. |
| Voraussetzungen | Alle drei Kriterien vor erster Mitigation. |
| Entry | Creator sucht Entry bereits im FVG vor/nahe dem Block und deckt den gesamten Block ab. |
| Bestätigung | CHoCH nach Sweep und FVG. |
| Invalidierung | Block wird vor CHoCH mitigiert; Kriterien fehlen. |
| Stop Loss | Sprachlich: gesamten Block abdecken; exakter Abstand nicht genannt. |
| Take Profit | Nicht spezifiziert. |
| Häufige Fehler | Jede letzte Gegenkerze als OB markieren; exakte Kante erzwingen. |
| Gegenbeispiel | Preis kann nur 50 % in den Block laufen oder bereits im FVG reagieren. |

## Widerspruch/Variante

V11 lässt nach vollständiger Validierung eine spätere Teilmitigation bis etwa 50 % zu. V13 behandelt einen bereits getesteten FVG strenger. Das sind unterschiedliche Objekttypen und Regeln; eine Gleichsetzung „jeder Touch invalidiert auch jeden Orderblock“ ist in der Playlist nicht belegt.

## Quellen dieses Abschnitts

- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE

---

# 16 Breaker Blocks

Keines der 13 ausgewerteten Playlist-Transkripte definiert einen Breaker Block oder liefert dafür Erkennungs-, Entry-, Invalidierungs-, Stop- oder Take-Profit-Regeln. Um die Vorgabe „keine erfundenen Regeln“ einzuhalten, enthält dieses Kapitel bewusst keine externe Definition.

Verwandte, aber nicht gleichzusetzende Playlist-Inhalte sind:

- ein gebrochener oder mitigierter Orderblock (V11/V12);
- ein altes Support-/Resistance-Level, das nach dem Bruch seine Rolle wechselt (V06);
- ein missachtetes FVG als frühes Reversal-Signal (V10).

Die Playlist nennt keines davon ausdrücklich „Breaker Block“. Eine solche Umbenennung wäre eine Interpretation der auswertenden KI und unterbleibt.

## Quellen dieses Abschnitts

- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8

---

# 17 Fair Value Gaps

## 17.1 Konstruktion

Ein bullisches FVG entsteht nach V05/V13 in einer Drei-Kerzen-Sequenz, wenn zwischen dem High/oberen Docht der ersten und dem Low/unteren Docht der dritten Kerze ein unüberlappter Bereich verbleibt. Bearish gilt das spiegelverkehrt. Ohne Abstand zwischen erster und dritter Kerze liegt nach V05 kein FVG vor.

Die Videos erklären FVGs als Imbalance einer schnellen, einseitigen Bewegung. Die Behauptung, der Markt „wolle“ diesen Bereich später ausgleichen, ist die Modellbeschreibung der Creator, keine Garantie.

## 17.2 Qualitätsfilter aus V05

1. **Orderflow:** bullische FVGs nur im Aufwärtstrend, bärische nur im Abwärtstrend.
2. **Frische:** unberührte FVGs bevorzugen.
3. **Premium/Discount:** Long-FVGs unterhalb der 50-%-Mitte des betrachteten Moves; Short-FVGs oberhalb.
4. **MTF-Nesting:** z. B. 15M-FVG innerhalb eines 4H-FVG für engeren Entry.
5. **Dritte Kerze:** Gegenkerze mit sichtbarer Stärke erzeugt im Video ein zu meidendes „rejection FVG“; zusätzliche Impulskerze in Gap-Richtung erzeugt ein bevorzugtes „breakaway gap“.
6. **Liquidity Run:** besonders bevorzugt wird ein trendgerichtetes FVG im Move, der externe Liquidität impulsiv durchläuft.
7. **Konsolidierung vermeiden:** alternierend scheiternde FVGs als Warnsignal; auf zwei neue respektierte FVGs warten.

## 17.3 Sechs Validitätsfaktoren aus V13

1. FVG muss unmitigiert/ungetestet sein.
2. Reaktionskerze darf durchwicken, soll aber im FVG oder in Richtung der Zone schließen; Close vollständig jenseits macht es ungültig.
3. Vorheriger Support bei bullishen bzw. Resistance bei bearishen FVGs als Confluence.
4. Bei mehreren bullishen FVGs priorisiert V13 das tiefste; bei bearishen das höchste.
5. Mit einer 0/0,5/1-Range sollen Long-FVGs in der unteren, Short-FVGs in der oberen Hälfte liegen.
6. Vor Entstehung bzw. im Entstehungsmove muss ein BOS des vorherigen Hochs/Tiefs erfolgen.

## 17.4 Expliziter Widerspruch zur Mitigation

- **V05:** Schon ein kleiner Touch macht das FVG „mitigated“ und schwächer; es müsse beim zweiten Besuch nicht zwangsläufig scheitern.
- **V13:** Nach einem Test gilt das FVG für die vorgestellte Strategie als ungültig und soll nicht mehr gehandelt werden.

Beide Regeln bleiben getrennt. Die Playlist liefert keinen gemeinsamen Backtest, der eine der beiden Varianten als überlegen beweist.

## Regelkarte: FVG-Retest nach V13

| Feld | Regel |
|---|---|
| Konzept | Erster Rücklauf in ein priorisiertes, unmitigiertes FVG nach BOS. |
| Erkennung | Drei-Kerzen-Gap; auf richtiger Range-Hälfte; S/R-Confluence bevorzugt. |
| Timeframe | Nicht festgelegt. |
| Marktumfeld | Strukturbruch und gerichteter Impuls; nicht als isoliertes Gap. |
| Voraussetzungen | Ungetestet, BOS, richtige Premium-/Discount-Seite. |
| Entry | Wenn Reaktionskerze im FVG oder in Zonenrichtung schließt. |
| Bestätigung | Candle-Close respektiert Zone; Wick durch Zone erlaubt. |
| Invalidierung | Close durch das FVG; vorherige Mitigation; kein BOS. |
| Stop Loss | Am Low der Kerze, die das bullische FVG erzeugte; spiegelverkehrt bearish. |
| Take Profit | Hoch des Moves; bearish spiegelverkehrt. |
| Häufige Fehler | Oberstes bullisches FVG statt tiefstem priorisieren; getestetes FVG wiederverwenden. |
| Gegenbeispiel | V05 bewertet einen erneuten Besuch nur als schwächer, nicht zwingend ungültig. |

## Quellen dieses Abschnitts

- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI

---

# 18 IFVG

Der Begriff **Inversion Fair Value Gap (IFVG)** und ein dazugehöriges Entry-Modell werden in den 13 Playlist-Transkripten nicht explizit definiert. V10 beschreibt zwar, dass die Missachtung eines bullischen FVG ein frühes Zeichen für einen Wechsel des Orderflows sein kann. Das Video nennt dieses missachtete FVG jedoch nicht IFVG und fordert anschließend CHoCH, ein neues bärisches FVG und BOS.

Deshalb wird aus der Missachtung nicht eigenmächtig folgende, externe Regel gemacht: „altes bullisches FVG wird automatisch bärischer Widerstand“. Diese Regel steht so nicht in den ausgewerteten Playlist-Videos.

## Quellen dieses Abschnitts

- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4

---

# 19 Entries

## 19.1 Katalog der expliziten Entry-Trigger

| Entry-Modell | Auslöser | Quelle |
|---|---|---|
| HTF-S/R + LTF-Break | HTF-Zone, dann Bruch von Trendlinie/Pivot/Key Area. | V04 |
| FVG-Retest im Trend | Rücklauf in bullisches FVG im Aufwärtstrend bzw. bärisches im Abwärtstrend. | V05 |
| Nested FVG | Entry am 15M-FVG innerhalb eines 4H-FVG. | V05 |
| Trendline Break-Retest | Impulsiver Break, zweiter BOS, Retest des neuen Levels/FVG. | V06 |
| Trendline Continuation | Schwacher Stich unter Linie, bullish Engulfing; aggressiv direkt oder konservativ nach neuem HH und Retest. | V06 |
| Chart-Pattern Break | Ausbruch aus Flag, Pennant, Wedge, Triangle, Neckline oder enger Range. | V07 |
| Breakout Momentum-Close | Große Body-Kerze mehrheitlich außerhalb oder dritte gleichgerichtete Kerze. | V08 |
| Supply/Demand Retest | Erste Rückkehr in validierte Zone; langsame Annäherung. | V09 |
| Sweep-Reversal FVG | Erstes FVG nach Sweep, FVG-Missachtung, CHoCH und BOS. | V10 |
| Orderblock/FVG | Entry bereits im FVG vor dem vollständig abgedeckten OB. | V11 |
| Inducement + LTF-Imbalance | True zone erreicht, 15M-BOS, Rücklauf in LTF-Imbalance. | V12 |
| Validiertes FVG | Erste Reaktion schließt im FVG oder in Zonenrichtung. | V13 |

## 19.2 Aggressiv versus bestätigt

V06 nennt beim Trendlinien-Continuation-Beispiel zwei Varianten: direkt am bullish Engulfing long oder nach mehr Bestätigung – neues höheres Hoch und Retest des zu Support gewordenen Widerstands. V08 bevorzugt beim Breakout den sofortigen Momentum-Close, weil ein direkter Move sonst verpasst werden könne. V04 und V10 warnen dagegen vor blindem Entry am bloßen Level. Diese Unterschiede sind Entry-Stile der Creator, keine einheitliche Playlist-Regel.

## Quellen dieses Abschnitts

- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 20 Stop Loss

## 20.1 Quellbasierte Platzierungen

| Setup | Stop-Platzierung im Video |
|---|---|
| Breakout über Resistance | Knapp unter gebrochenem Resistance-Level (V08). |
| Trendline Fakeout Short | Über dem gesweepten/reaktionsbildenden Hoch (V06). |
| Trendline Continuation Long | Unter dem neuen Support bzw. im späteren Beispiel unter dem FVG (V06). |
| Demand Retest | Unter der Demand-Zone (V09). |
| Supply Retest | Über der Supply-Zone (V09). |
| Orderblock nach V11 | Gesamten Orderblock „abdecken“; kein fixer Tick-/ATR-Abstand genannt. |
| Inducement-Orderblock Long | Unter dem Higher-Timeframe-Tief (V12). |
| FVG-Retest nach V13 | Am Low der Kerze, die das bullische FVG erzeugte; bearish spiegelverkehrt. |
| Flag/Pennant/Wedge/Range | Auf der Gegenseite der Formation, wie in V07 schematisch gezeigt. |

## 20.2 Was die Playlist nicht festlegt

Keine Playlist-Quelle gibt eine allgemeine ATR-basierte Initial-Stop-Formel, einen festen Prozentabstand, einen universellen Buffer oder eine Slippage-Regel vor. Der Chandelier Stop in V08 steuert den Exit der Restposition, nicht den anfänglichen Stop. Solche fehlenden Regeln werden nicht ergänzt.

## Quellen dieses Abschnitts

- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 21 Take Profit

## 21.1 Zielmethoden aus der Playlist

- Vorheriges Hoch für Long bzw. vorheriges Tief für Short (V07, V09, V12, V13).
- „Nach links schauen“: frühere Hochs, Tiefs oder Rejection-Zonen als Ziel (V07).
- Nächster Support nach bearishen Fakeout bzw. nächste Resistance nach bullishen Gegenstück (V04).
- Nächste externe Range Liquidity / Buy-Side oder Sell-Side Liquidity (V10).
- Höhere bzw. tiefere Levels im Trendlinienmodell (V06).
- Teilgewinn bei 1,5R, Rest nach Chandelier-Stop-Farbwechsel (V08).

## 21.2 Kein universelles Ziel

Die Videos verwenden unterschiedliche Ziele je nach Setup. Die Wissensbasis setzt daraus nicht eigenmächtig ein einheitliches System zusammen. Besonders V10 sagt: Soll über das lokale Liquiditätsziel hinaus gehalten werden, muss die größere Timeframe-Struktur geprüft werden.

## Quellen dieses Abschnitts

- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 22 Risk/Reward

## 22.1 R-Multiple-Logik aus V02

V02 erläutert, dass Profitabilität nicht 100 % Trefferquote verlangt. Bei einem beispielhaften Verhältnis von 3:1 werden 100 Euro riskiert, um 300 Euro zu gewinnen. Ein Verlust und ein Gewinn ergäben vor Kosten netto +200 Euro. Ein weiteres Beispiel des Videos hat sechs Verlusttrades und drei Gewinntrades mit +4R, +5R und +4R; daraus resultieren +7R vor Kosten.

Der Creator sagt, bei 1:1 müsse die Trefferquote 50 % betragen und bei 3:1 seien 30 % profitabel. Mathematisch liegt der reine Break-even bei exakt 3:1 ohne Kosten bei 25 %. Die 30-%-Aussage wird daher als Creator-Aussage dokumentiert, nicht als exakte allgemeine Schwelle; Gebühren, Slippage und abweichende durchschnittliche Gewinne/Verluste verschieben den Break-even.

## 22.2 Setup-spezifische R-Regeln

- V07: Bei der engen Konsolidierungsformation keinen Trade nehmen, wenn nicht mehr als 2:1 erreichbar ist; der Creator erwartet eher eine Größenordnung um 5:1.
- V08: Erstes Ziel bei 1,5R, halbe Position schließen, Rest laufen lassen.
- V09 zeigt „gutes“ R:R durch Zone-zu-Extrem-Struktur, nennt aber keinen Mindestwert.

## 22.3 Erwartungswert – nur als Ableitung gekennzeichnet

Die Playlist liefert die Bausteine Gewinnrate, durchschnittlicher Gewinn und durchschnittlicher Verlust, aber keine ausgeschriebene Formel. Zur sauberen Interpretation der Video-Beispiele kann der Zusammenhang beschrieben werden als: Viele kleine Verluste können durch weniger, aber größere Gewinne überkompensiert werden. Eine konkrete Prozent-Risikoregel je Trade wird daraus nicht erfunden.

## Quellen dieses Abschnitts

- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI

---

# 23 Position Sizing

Die Playlist spricht über Risikobeträge und R-Multiples, gibt aber **keine vollständige Positionsgrößenformel** an. Insbesondere fehlen:

- festgelegter Prozentsatz des Kontos pro Trade;
- Formel aus Kontorisiko ÷ Stop-Distanz;
- Kontraktwert, Pip-/Tick-Wert oder Lot-Berechnung;
- Korrelation mehrerer offener Positionen;
- Tagesverlustlimit oder Maximalzahl gleichzeitiger Risiken.

V01 warnt, dass Hebel Gewinne und Verluste verstärkt und bei geliehenem Kapital Schulden entstehen können. V02 verwendet ein Beispiel mit 100 Euro Risiko, erklärt aber nicht, wie dieser Betrag aus einer Kontogröße abgeleitet wird. Deshalb wäre jede konkrete Sizing-Regel eine nicht erlaubte Ergänzung.

## Quellen dieses Abschnitts

- **In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)** — Finanzfluss — https://www.youtube.com/watch?v=W9rc0RQvf0s
- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78

---

# 24 Sessions

Die 13 Playlist-Transkripte definieren keine London-, New-York- oder Asia-Session, keine Killzones, keine Opening Ranges und keine zeitabhängigen Entry-Fenster. Auch Session-Überlappungen und instrumentenspezifische Handelszeiten werden nicht operationalisiert.

Die einzige zeitliche Grunddefinition aus V01 lautet: Daytrading-Positionen werden innerhalb desselben Handelstages geschlossen. Daraus darf keine Session-Strategie abgeleitet werden.

## Quellen dieses Abschnitts

- **In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)** — Finanzfluss — https://www.youtube.com/watch?v=W9rc0RQvf0s

---

# 25 News und Volatilität

## 25.1 Event Trading aus V01

V01 nennt als kursbewegende Ereignisse:

- Arbeitsmarktdaten;
- makroökonomische Prognosen und Veröffentlichungen;
- Zinsentscheidungen;
- unerwartete Nachrichten;
- Unternehmensumsätze bzw. Unternehmensdaten.

Die Reaktion hänge nicht nur vom absoluten Wert ab, sondern davon, wie das Ergebnis im Verhältnis zu den Erwartungen ausfällt. Eine Veröffentlichung kann also „gut“ aussehen und dennoch fallen, wenn der Markt mehr erwartet hatte – oder umgekehrt.

## 25.2 Fehlende operative Regeln

Die Playlist nennt keine konkrete Minuten-Sperre vor/nach News, keinen News-Kalender, keine Spread-/Slippage-Grenze und keinen positionsgrößenbezogenen Volatilitätsfilter. Auch V08/V09 sprechen von Momentum bzw. aggressiven Kerzen, verbinden dies aber nicht explizit mit Nachrichten. Solche Regeln werden daher nicht ergänzt.

## Quellen dieses Abschnitts

- **In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)** — Finanzfluss — https://www.youtube.com/watch?v=W9rc0RQvf0s

---

# 26 Trade Management

## 26.1 Vor dem Trade

V02 verlangt, Entry-Grund, Take Profit und Stop Loss vorab zu definieren und zu dokumentieren. V04/V10 verlangen, nicht blind am ersten Level einzusteigen, sondern auf den setupspezifischen Bestätigungspfad zu warten.

## 26.2 Während des Trades

Das detaillierteste Management liefert V08:

1. Initialer Stop hinter dem gebrochenen Level.
2. Erstes Ziel 1,5R.
3. Dort 50 % der Position realisieren.
4. Stop des Rests auf das alte TP-Level setzen – nicht bloß auf Entry.
5. Rest über Chandelier Stop mit ATR-Multiplikator 2 führen.
6. Bei Farbwechsel des Indikators schließen.

Andere Videos zeigen überwiegend statische Ziele: vorheriges Hoch/Tief, nächstes Level oder externe Liquidität. Ein Zusammenmischen – beispielsweise bei jedem Orderblock automatisch den Chandelier Stop verwenden – wird von der Playlist nicht gefordert.

## 26.3 Nach dem Trade

V02 empfiehlt, den Trade im Journal auszuwerten und Serien statt Einzelergebnisse zu beurteilen. Ein Gewinn validiert die Entscheidung nicht automatisch; ein Verlust invalidiert sie nicht automatisch.

## Quellen dieses Abschnitts

- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8

---

# 27 Trading Psychology

## 27.1 Prozess vor Einzelergebnis

V02 beschreibt als Kernfehler, wegen FOMO oder spontaner Marktmeinung ohne Regelwerk einzusteigen. Die Gegenregel lautet:

- Strategie und Risiko vorab definieren;
- Paper-Trades durchführen;
- Gründe für Entry und Exit aufschreiben;
- nach einer größeren Stichprobe überprüfen;
- guten Prozess nicht wegen eines einzelnen Verlusts verwerfen;
- schlechten Prozess nicht wegen eines zufälligen Gewinns feiern.

## 27.2 Psychologische Risiken aus V01

V01 nennt niedrige Einstiegshürden, professionelle Konkurrenz, Informations-/Technologienachteil, Hebel und potenziell suchtähnliches Verhalten als Risiken. Das Video stellt heraus, dass schnelle Handelsfrequenz und kurzfristige Belohnung problematisch werden können.

## 27.3 Keine Gewinnversprechen

Mehrere Playlist-Videos verwenden werbliche Formulierungen wie „highest probability“, „easy W“, „perfect trade“ oder zeigen einzelne Gewinne. V12 nennt sogar einen behaupteten Copy-Trading-Anstieg von 50.000 auf 160.000 und eine fremde 86-%-Winrate. Diese Angaben werden nicht als Beleg für reproduzierbare Profitabilität übernommen: Das Video zeigt keinen unabhängig geprüften Track Record, keine vollständige Verlustverteilung und keine risikoadjustierte Langzeitstatistik.

## Quellen dieses Abschnitts

- **In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)** — Finanzfluss — https://www.youtube.com/watch?v=W9rc0RQvf0s
- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE

---

# 28 Backtesting

V12 sagt, die Inducement-Methode sei nach Recherche, Backtesting und Analyse entstanden. Das Video legt jedoch weder Datensatz noch Märkte, Zeiträume, Gebühren, Sample-Größe, Regeln für In-/Out-of-sample-Trennung oder Kennzahlen offen. V02 empfiehlt eine Serie von mindestens 100 Paper-Trades, was Forward-Simulation bzw. Übung ist, aber nicht als vollständiges historisches Backtest-Protokoll beschrieben wird.

Damit liefert die Playlist **keine vollständige Backtesting-Methode**. Aus den Videos lassen sich nur folgende quellentreue Anforderungen an die zu testenden Regeln ableiten:

- Entry, Stop und Target müssen vor der Auswertung eindeutig notiert sein (V02).
- Varianten dürfen nicht nachträglich vermischt werden, etwa FVG nach V05 versus V13.
- Kosten sind relevant und können hohe Handelsfrequenz belasten (V01).
- Nicht nur Gewinne, sondern auch Verlustserien und R-Multiples betrachten (V02).

Eine konkrete Kennzahlenliste wie Profit Factor, Maximum Drawdown oder Monte-Carlo-Test wird nicht ergänzt, weil sie in den Transkripten nicht vorkommt.

## Quellen dieses Abschnitts

- **In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)** — Finanzfluss — https://www.youtube.com/watch?v=W9rc0RQvf0s
- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE

---

# 29 Journaling

V02 empfiehlt sowohl physisches als auch digitales Journal. Vor jedem Trade sollen mindestens der Grund für den Entry, der Take Profit und der Stop Loss feststehen. Danach wird geprüft, ob der Trade regelkonform war. Nach ungefähr einem Monat bzw. einer ausreichenden Serie soll ausgewertet werden, welche Fehler wiederkehren.

## Quellbasierte Journalfelder

Die folgende Liste besteht nur aus Punkten, die in V02 direkt verlangt oder in den Playlist-Setups zwingend zur Rekonstruktion benötigt werden:

- Datum und gehandelter Markt;
- beobachteter Timeframe bzw. MTF-Kombination;
- Grund/Setup für den Entry;
- Entry-Preis bzw. Entry-Bereich;
- vorab definierter Stop Loss;
- vorab definiertes Take Profit;
- erwartetes R:R;
- Ergebnis in Gewinn/Verlust bzw. R;
- ob die Regel eingehalten wurde;
- ob FOMO/spontane Diskretion beteiligt war;
- Screenshot bzw. visuelle Dokumentation ist in V07 für das Lernen von Mustern empfohlen, aber nicht ausdrücklich als Pflichtfeld jedes Journals bezeichnet.

## Quellen dieses Abschnitts

- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc

---

# 30 Komplette Trading-Setups

Die folgenden Setups sind **getrennte Video-Modelle**. Sie sind keine kombinierte Master-Strategie der auswertenden KI.

## Setup A — Momentum-Breakout mit Zwei-Stufen-Exit (V08)

| Feld | Regel |
|---|---|
| Konzept | Break aus einer Konsolidierung mit Momentum-Bestätigung. |
| Erkennung | Support/Resistance mit mehreren Rejections; Form kann Rectangle, Wedge, Flag, Triangle oder Pennant sein. |
| Timeframe | Nicht spezifiziert. |
| Marktumfeld | Konsolidierung vor möglichem Expansion-Move. |
| Voraussetzungen | Große Body-Kerze überwiegend jenseits des Levels oder drei mittelgroße Kerzen gleicher Richtung. |
| Entry | Close der Momentum-Kerze bzw. der dritten Bestätigungskerze. |
| Bestätigung | Körper statt nur Docht außerhalb. |
| Invalidierung | Rückkehr durch Level/Stop; kleine Kerzen ohne Momentum werden ignoriert. |
| Stop Loss | Knapp hinter gebrochenem Level. |
| Take Profit | 50 % bei 1,5R; Rest bei Chandelier-Stop-Farbwechsel, ATR-Multiplikator 2. |
| Häufige Fehler | Sofort beim ersten Docht-Break einsteigen; perfektes Pattern-Bild verlangen. |
| Gegenbeispiel | Direkter Move ohne Pullback – deshalb bevorzugt V08 den sofortigen Momentum-Close. |

## Setup B — Trendlinien-Fakeout Short (V06)

| Feld | Regel |
|---|---|
| Konzept | Schwacher Ausbruch in Liquidität, danach bearish Strukturbruch. |
| Erkennung | Mindestens zwei Swing-High-Anker; dritter Kontakt/brüchige Bewegung über Linie; nahe Equal Highs. |
| Timeframe | Nicht spezifiziert. |
| Marktumfeld | Vorherige Abwärtsstärke größer als aktueller Aufwärtsbreak. |
| Voraussetzungen | Ausbruchskerzen klein/nicht impulsiv. |
| Entry | Nach bearish Engulfing und Bruch des Swing Lows beim Rücklauf in neu entstandenes FVG. |
| Bestätigung | Swing-Low-Bruch bestätigt bearishen Trend im Beispiel. |
| Invalidierung | Echter impulsiver Ausbruch mit Folgekerzen und weiterem BOS. |
| Stop Loss | Über dem Hoch. |
| Take Profit | Tiefere Levels. |
| Häufige Fehler | Zwei Closes über Trendlinie automatisch als echten Break werten. |
| Gegenbeispiel | Große energetische Break-Kerzen plus Folgebewegung signalisieren eher echten Break. |

## Setup C — Supply/Demand First Retest (V09)

| Feld | Regel |
|---|---|
| Konzept | Rücklauf in Ursprungskerze eines aggressiven, strukturbrechenden Moves. |
| Erkennung | Letzte Gegenkerze vor Impuls; Zone von Low bis High. |
| Timeframe | Nicht spezifiziert. |
| Marktumfeld | Klarer impulsiver Move. |
| Voraussetzungen | BOS; bevorzugt FVG am Ursprung; langsame Rückkehr. |
| Entry | Beim Eintritt in die Zone. |
| Bestätigung | Kriterien werden vor dem Retest geprüft; keine separate Reaktionskerze verlangt. |
| Invalidierung | Scharfer aggressiver Rücklauf; kein BOS. |
| Stop Loss | Hinter der Zone. |
| Take Profit | Extrem des ursprünglichen Moves. |
| Häufige Fehler | Schwachen Drift als Zone markieren; aggressive Rückkehr handeln. |
| Gegenbeispiel | Zone ohne FVG könne funktionieren, sei laut Creator aber schwächer. |

## Setup D — MTF Liquidity Sweep Reversal (V10)

| Feld | Regel |
|---|---|
| Konzept | LTF-Umkehr in HTF-FVG in Richtung des HTF-Orderflows. |
| Erkennung | 4H-BOS und FVG; 15M läuft lokal dagegen in den Bereich. |
| Timeframe | 4H → 15M; Weekly zur größeren Einordnung. |
| Marktumfeld | Bullischer HTF-Trend mit bearishen LTF-Retracement; bearish spiegelverkehrt. |
| Voraussetzungen | Externes Ziel und internes FVG bestimmt. |
| Entry | Erstes FVG nach komplettem LTF-Reversal. |
| Bestätigung | Sweep → altes FVG missachtet → CHoCH → BOS. |
| Invalidierung | Reversal-Sequenz unvollständig; HTF-Bereich wird nicht respektiert. |
| Stop Loss | Im Video für das konkrete Beispiel nicht präzisiert. |
| Take Profit | Gegenüberliegende 4H-ERL. |
| Häufige Fehler | Am Sweep selbst einsteigen; größere Weekly-Struktur ignorieren. |
| Gegenbeispiel | 4H-Long kann in Weekly-bearishem FVG liegen und daher nur lokaler Trade sein. |

## Setup E — Orderblock nach Noc Trading (V11)

| Feld | Regel |
|---|---|
| Konzept | Letzte Kerze vor Richtungswechsel, dreifach validiert. |
| Erkennung | Sweep links, FVG/Displacement, CHoCH. |
| Timeframe | Laut Creator jeder Timeframe. |
| Marktumfeld | Reversal. |
| Voraussetzungen | Unmitigiert bis nach CHoCH. |
| Entry | Persönliche Variante des Creators: bereits im FVG, gesamten OB abdecken. |
| Bestätigung | Alle drei Kriterien. |
| Invalidierung | Vorzeitige Mitigation oder fehlender CHoCH. |
| Stop Loss | Hinter/über den gesamten Block; exakter Buffer nicht spezifiziert. |
| Take Profit | Nicht spezifiziert. |
| Häufige Fehler | Beliebige letzte Kerze als OB; exakten Kantentreffer verlangen. |
| Gegenbeispiel | Reaktion kann im FVG oder bei ca. 50-%-Mitigation erfolgen. |

## Setup F — Inducement-Orderblock (V12)

| Feld | Regel |
|---|---|
| Konzept | Schwache Zone wird gebrochen, danach Entry aus der strukturwirksamen True Zone. |
| Erkennung | Mehrere Zonen; Imbalance und verursachter Strukturbruch unterscheiden Inducement von True Zone. |
| Timeframe | 1H-Zone, 15M-Bestätigung im Beispiel. |
| Marktumfeld | Klarer Trend mit HH/HL für Long. |
| Voraussetzungen | Inducement wird gebrochen; Preis erreicht True Zone. |
| Entry | 15M-BOS zur bullischen Struktur, danach Rücklauf in 15M-Imbalance. |
| Bestätigung | LTF-Strukturwechsel. |
| Invalidierung | Nicht spezifiziert außer Stop unter HTF-Tief. |
| Stop Loss | Unter Higher-Timeframe-Tief. |
| Take Profit | Vorheriges Hoch. |
| Häufige Fehler | Tiefste Zone automatisch wählen; schwachen Wick-Bruch als echten Strukturbruch werten. |
| Gegenbeispiel | Tiefste Zone kann zu weit entfernt sein und nie erreicht werden; mittlere Zone kann den echten BOS verursacht haben. |

## Setup G — Sechs-Faktoren-FVG (V13)

| Feld | Regel |
|---|---|
| Konzept | Erster Test eines priorisierten FVG nach BOS. |
| Erkennung | Drei-Kerzen-Gap. |
| Timeframe | Nicht spezifiziert. |
| Marktumfeld | Gerichteter Impuls nach Strukturbruch. |
| Voraussetzungen | Unmitigiert, S/R-Confluence, richtige Range-Hälfte, höchstrangiges Gap. |
| Entry | Reaktionskerze schließt im Gap oder in Zonenrichtung. |
| Bestätigung | Wick durch Zone erlaubt, Close jenseits nicht. |
| Invalidierung | Frühere Mitigation, Close durch Gap, kein BOS. |
| Stop Loss | Low/High der Gap-erzeugenden Kerze. |
| Take Profit | Hoch/Tief des Moves. |
| Häufige Fehler | Erstbestes FVG handeln; Premium/Discount ignorieren. |
| Gegenbeispiel | V05 sieht getestete FVGs nur als schwächer, nicht automatisch tot. |

## Quellen dieses Abschnitts

- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 31 Pre-Trade Checklist

Diese Checkliste ist eine **Indexierung der in den Videos genannten Fragen**, keine neue Strategie. Pro Trade dürfen nur die Punkte des gewählten Quellen-Setups angewendet werden.

- [ ] Welches konkrete Video-Setup wird getestet? Keine Regelmischung ohne getrennte Auswertung (V02).
- [ ] Ist der Higher-Timeframe-Orderflow bullish, bearish oder unklar (V05/V10)?
- [ ] Liegt eine erkennbare Trendstruktur oder eine Konsolidierung vor (V05)?
- [ ] Welche Buy-Side-/Sell-Side-Liquidität ist das externe Ziel (V10)?
- [ ] Ist das Level eine Zone statt einer scheinbar exakten Linie (V04)?
- [ ] Ist der relevante Swing-/BOS-Punkt vor Entry festgelegt (V09/V10/V13)?
- [ ] Ist die Zone/FVG frisch oder bereits mitigiert, und welche Quellenvariante gilt (V05 versus V13)?
- [ ] Liegt der Long-Bereich in Discount bzw. Short-Bereich in Premium, falls das gewählte FVG-Modell dies verlangt (V05/V13)?
- [ ] Ist der Impuls wirklich aggressiv und hat er Struktur gebrochen (V09)?
- [ ] Nähert sich Preis langsam an Supply/Demand, falls dieses Setup gehandelt wird (V09)?
- [ ] Besteht beim Breakout echte Body-/Mehrkerzen-Momentum-Bestätigung (V08)?
- [ ] Sind Entry, Stop, Ziel und R:R vorab notiert (V02)?
- [ ] Liegt das Ziel an einem im Video erlaubten Level und nicht an einer erfundenen Projektion?
- [ ] Ist bei MTF-Setup die LTF-Bestätigungssequenz vollständig (V10/V12)?
- [ ] Wird ein einzelnes Candlestick-Muster fälschlich ohne Kontext gehandelt (V03)?

## Quellen dieses Abschnitts

- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **The ONLY Candlestick Pattern Guide You'll EVER NEED** — TradingLab — https://www.youtube.com/watch?v=tW13N4Hll88
- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 32 No-Trade Checklist

- [ ] Kein klares Quellen-Setup bzw. Entry basiert auf FOMO oder spontaner Meinung (V02).
- [ ] Blindes Limit an Support/Resistance ohne zusätzliche Bestätigung (V04).
- [ ] Zu viele widersprüchliche LTF-Levels erzeugen Clutter (V04).
- [ ] Bullische und bärische FVGs scheitern abwechselnd: mögliche Konsolidierung (V05).
- [ ] FVG gegen den aktuellen Orderflow (V05).
- [ ] Rejection-FVG: dritte Kerze zeigt starke Gegenrichtung (V05).
- [ ] Trendlinienbreak nur mit kleinen, energiearmen Kerzen (V06).
- [ ] Symmetric Triangle ohne dramatisch bestätigten Richtungsbreak (V07).
- [ ] Enge Range bietet nicht mehr als 2:1 im V07-Modell (V07).
- [ ] Breakout besteht nur aus Docht/kleiner Körperspitze (V08).
- [ ] Supply/Demand-Move war nicht aggressiv oder brach keine Struktur (V09).
- [ ] Rücklauf in Supply/Demand ist scharf und aggressiv (V09).
- [ ] Sweep wird ohne nachfolgende Struktur gelesen (V10).
- [ ] Orderblock wurde vor CHoCH bereits mitigiert (V11).
- [ ] Zone wird nur gewählt, weil sie die tiefste/höchste ist, ohne Strukturursprung zu prüfen (V12).
- [ ] Nach V13 bereits getestetes FVG; nach V05 zumindest deutlich herabstufen und getrennt testen.

## Quellen dieses Abschnitts

- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 33 Fehlerkatalog

| Fehler | Warum laut Playlist problematisch | Korrektur aus der Quelle |
|---|---|---|
| Einzelgewinn mit guter Strategie verwechseln | Gewinn kann Zufall sein. | Prozess und Serie journalen (V02). |
| Einzelverlust als Beweis gegen Setup | Guter Trade kann verlieren. | Regelkonformität getrennt vom Ergebnis bewerten (V02). |
| Candlestick isoliert handeln | Muster sind nur Hinweise. | Mit S/R, Struktur oder Strategie kombinieren (V03). |
| S/R als exakte Linie | Volatilität erzeugt Überschreitungen. | Als Zone behandeln (V04). |
| Zu viele Levels | Clutter und Zögern. | HTF-Major-Levels priorisieren, irrelevante löschen (V04). |
| Blind am HTF-Level einsteigen | Reaktion ist nicht bestätigt. | LTF-Break/Confluence abwarten (V04). |
| FVG gegen Orderflow | Retracement-Logik widerspricht Trend. | Bullisch in Uptrend, bearish in Downtrend (V05). |
| Mitigiertes FVG wie frisch behandeln | V05 stuft es schwächer, V13 verwirft es. | Quellenvariante festlegen und getrennt testen. |
| Konsolidierung als Trend | Richtungswechsel choppt Entries. | Auf zwei neue respektierte FVGs warten (V05). |
| Trendlinie an Bias anpassen | Inkonsistente Anker erzeugen Scheinsignal. | Wicks oder Bodies konsistent nutzen (V06). |
| Kleinen Trendline-Stich als echten Break handeln | Keine sichtbare Energie/Folge. | Impuls, Folgekerzen und optional zweiten BOS verlangen (V06). |
| Perfektes Pattern-Bild suchen | Reale Preisbewegung ist unregelmäßig. | Funktionale Begrenzungen/Levels lesen (V07/V08). |
| Docht-Breakout kaufen | Häufiger Fakeout im Beispiel. | Body überwiegend außerhalb oder drei Kerzen (V08). |
| Jede Gegenkerze als Supply/Demand | Ohne Aggression/BOS fehlt Validierung. | Impuls + BOS, bevorzugt FVG (V09). |
| Aggressiven Rücklauf in Zone handeln | V09 wertet ihn als Warnsignal. | Langsame, stetige Annäherung verlangen. |
| CHoCH sofort als Umkehr | Kann Sweep sein. | Danach BOS der neuen Richtung abwarten (V10). |
| Nur Reaktion am Liquiditätslevel traden | Run/Sweep ist noch nicht strukturell entschieden. | FVG- und Strukturfolge lesen (V10). |
| Jede letzte Kerze als Orderblock | V11 verlangt drei Kriterien. | Sweep + FVG + CHoCH vor Mitigation. |
| Tiefste Zone automatisch wählen | Sie kann nicht strukturwirksam sein oder unerreicht bleiben. | Zone des echten Strukturbruchs bestimmen (V12). |
| Werbe-Profit als Evidenz | Keine vollständige Statistik/Verifikation. | Behauptung getrennt von Regelwissen dokumentieren. |

## Quellen dieses Abschnitts

- **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
- **The ONLY Candlestick Pattern Guide You'll EVER NEED** — TradingLab — https://www.youtube.com/watch?v=tW13N4Hll88
- **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
- **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
- **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
- **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc
- **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
- **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
- **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
- **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
- **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
- **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

---

# 34 Glossar

| Begriff | Bedeutung innerhalb der Playlist |
|---|---|
| Body | Bereich zwischen Open und Close einer Kerze. |
| Wick/Docht | Bewegung vom Kerzenkörper zum Periodenhoch/-tief. |
| Bullish/Bearish | Auf steigende bzw. fallende Preisrichtung bezogen. |
| HH / HL | Higher High / Higher Low; Bausteine eines Aufwärtstrends. |
| LL / LH | Lower Low / Lower High; Bausteine eines Abwärtstrends. |
| Support | Horizontaler/zonaler Bereich, an dem Käuferreaktion erwartet/beobachtet wird. |
| Resistance | Bereich, an dem Verkäuferreaktion erwartet/beobachtet wird. |
| Trendline | Diagonaler Support/Widerstand durch mindestens zwei signifikante Swingpunkte. |
| BOS | Break of Structure; in V10 Bruch in aktueller Trendrichtung. |
| CHoCH | Change of Character; erster Bruch gegen bisherigen Orderflow, noch keine vollständig bestätigte Umkehr. |
| MSS | In der Playlist nicht eigenständig definiert; V12 nutzt „structural shift“ allgemein. |
| ERL | External Range Liquidity an vorherigem Swing High/Low. |
| IRL | Internal Range Liquidity; in V10 mit FVGs innerhalb eines Swings gleichgesetzt. |
| Buy-Side Liquidity | Liquidität am/über Swing High. |
| Sell-Side Liquidity | Liquidität am/unter Swing Low. |
| Liquidity Run | Fortsetzung durch externes Liquiditätslevel, in V10 mit neuem trendgerichtetem FVG validiert. |
| Liquidity Sweep | Angriff auf externes Level mit anschließender Umkehr. |
| FVG | Fair Value Gap; unüberlappter Bereich zwischen Kerze 1 und 3 einer impulsiven Drei-Kerzen-Sequenz. |
| Mitigation | Erster Rücklauf/Touch einer Zone oder eines FVG. |
| Premium | Obere Hälfte einer markierten Range; von V05/V13 für Shorts bevorzugt. |
| Discount | Untere Hälfte; von V05/V13 für Longs bevorzugt. |
| Rejection FVG | Begriff aus V05 für FVG, dessen dritte Kerze stark gegen die Gap-Richtung reagiert. |
| Breakaway Gap | Begriff aus V05 für FVG mit zusätzlicher impulsiver dritter Kerze in Bewegungsrichtung. |
| Orderblock | In V11 letzte Kerze vor Richtungswechsel, nur valide mit Sweep, FVG und CHoCH. |
| Inducement | In V12 scheinbar attraktive schwache Zone/Falle vor der „true zone“. |
| Supply/Demand | Ursprung aggressiven Verkaufs/Kaufs; V09 markiert letzte Gegenkerze vor Impuls. |
| Momentum Candle | Große Body-Kerze bzw. in V08 alternativ drei mittelgroße Kerzen gleicher Richtung. |
| Fakeout | Scheinbarer Break, der nicht fortsetzt und zurückkehrt. |
| R | Einheit des vorab riskierten Betrags. |
| Chandelier Stop | In V08 ein ATR-basierter Indikator für den Exit der Restposition, Multiplikator 2. |
| Confluence | Zusammentreffen mehrerer unabhängiger im Video genannter Hinweise. |
| Silver Bullet | In V10 Bezeichnung für das erste FVG nach bestätigtem LTF-Reversal. |
| Breaker Block | In der Playlist nicht definiert. |
| IFVG | In der Playlist nicht definiert. |

## Quellen dieses Abschnitts

- **Alle 13 Playlist-Videos**, vollständig aufgelistet in Kapitel 35 und `video_sources.md`.

---

# 35 Quellen

## Primärplaylist – vollständig erfasst

1. **In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)** — Finanzfluss — https://www.youtube.com/watch?v=W9rc0RQvf0s
2. **Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)** — Henry F. — https://www.youtube.com/watch?v=B6xG-m2fn78
3. **The ONLY Candlestick Pattern Guide You'll EVER NEED** — TradingLab — https://www.youtube.com/watch?v=tW13N4Hll88
4. **Secret Formula For Drawing Support & Resistances** — TradingLab — https://www.youtube.com/watch?v=9NbmBDUysOA
5. **FVG Trading Strategy Explained (Fair Value Gaps)** — Trader Tips — https://www.youtube.com/watch?v=yJDaddL6SB4
6. **The ONLY Trendline Trading Video You NEED in 2026!** — TradingLab — https://www.youtube.com/watch?v=8nIoOnGOZU8
7. **Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen** — The Moving Average — https://www.youtube.com/watch?v=WbMnfiknBoc
8. **How to Avoid False Breakouts (My Secret Technique)** — TradingLab — https://www.youtube.com/watch?v=ZudTPpJCbbA
9. **The ULTIMATE Supply & Demand Guide (My Secrets)** — TradingLab — https://www.youtube.com/watch?v=fPSQ_NnmqWI
10. **Liquidity Sweep Trading Strategy Explained** — Trader Tips — https://www.youtube.com/watch?v=Skn0eSmryO8
11. **So erkennst du einen Orderblock** — Noc Trading — https://www.youtube.com/watch?v=AwxIbna0By4
12. **I Found a Secret To Orderblocks** — TradingLab — https://www.youtube.com/watch?v=qmsGqitE2LE
13. **I Found A Secret To Fair Value Gaps** — TradingLab — https://www.youtube.com/watch?v=ZTMregh_428

Playlist: https://youtube.com/playlist?list=PLK8g_u70zjYP1fhJL2ExzGVu9MpgkE_Kd

## Abdeckungs- und Integritätshinweise

- Jedes Playlist-Video wurde einzeln geöffnet und seine verfügbare YouTube-Untertitelspur ausgewertet.
- Für V11 endet die von YouTube ausgelieferte automatische Spur bei 04:03, obwohl das Video 06:47 lang ist. Aussagen aus dem nicht transkribierten Rest wurden nicht erfunden.
- Die separat geforderte Zusatzrecherche wurde auf YouTube mit 14 Themenabfragen begonnen und 329 einzigartige Kandidaten wurden erfasst. YouTube blockierte anschließend alle zusätzlichen Caption-Abfragen mit einem automatisierten Traffic-/Rate-Limit. Deshalb werden diese Kandidaten **nicht** als analysierte Quellen ausgegeben und keine Regeln aus Titel, Beschreibung oder Vermutung übernommen.
- Eine vollständige Audit-Tabelle zu Transcript-Art, Sprache und Kapitelzuordnung steht in `video_sources.md`.

## Quellen dieses Abschnitts

- **Trading by Loma (Playlist)** — YouTube — https://youtube.com/playlist?list=PLK8g_u70zjYP1fhJL2ExzGVu9MpgkE_Kd

