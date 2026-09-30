---
typ: wissensbasis
thema: Trading-Analyse-Grundlagen
status: research-v2-enzyklopaedisch
aktualisiert: 2026-09-30
sprache: de
quellenfokus: YouTube
verwandt:
  - "[[DAYTRADING_MASTER_GUIDE]]"
  - "[[video_sources]]"
---

# Trading-Analyse-Grundlagen — Bausteine statt Strategie

> [!important] Zweck
> Diese Notiz beschreibt **Analysebausteine**, keine fertige Handelsstrategie. Sie soll einem Obsidian-basierten Analysesystem sagen, *was* ein Merkmal ist, *welche Daten* dafür nötig sind, *was beobachtet werden kann* und *was daraus nicht automatisch folgt*. Entry, Stop-Loss, Take-Profit und Positionsgröße werden hier bewusst nicht zu einem Setup verbunden.

> [!warning] Realitätsgrenze
> Vollständigkeit bedeutet hier: möglichst vollständige Begriffs-, Kausal- und Prüfstruktur. Sie bedeutet **nicht**, dass ein Dokument Markterfahrung ersetzt oder eine hundertprozentige Trefferquote erzeugt. Ein professionelles Modell muss Unsicherheit, Kosten, Datenfehler, Regimewechsel und Verlustserien ausdrücklich abbilden.

## 0. Quellen- und Evidenzregeln

- **A — Volltranskript ausgewertet:** Aussage darf als konkrete Creator-Regel gespeichert werden. Dazu gehören die 13 Videos der Primärplaylist `[P01–P13]` und das vollständige veröffentlichte Video-Transkript `[Z02]`.
- **B — substantieller Transkript-/Kapiteltext ausgewertet:** Nur die ausdrücklich sichtbaren Definitionen und Grenzen dürfen übernommen werden; keine fehlenden Regeln ergänzen. `[Z01]`, `[Z03–Z18]`.
- **C — YouTube-Kandidat:** Titel, Creator, Laufzeit und Thema sind erfasst, aber es wurde wegen nicht ausgeliefertem Transkript keine Fachregel daraus übernommen. 329 solcher Kandidaten liegen in `research/supplemental/candidates.json`.
- Eine Creator-Aussage über „Profitabilität“, „Trefferquote“, „Smart Money“ oder „institutionelle Nutzung“ ist eine **Behauptung des Creators**, kein unabhängiger Nachweis.
- Begriffe wie BOS, CHoCH, MSS, Order Block oder Fair Value Gap sind **Framework-Begriffe**. Mehrere Creator verwenden dieselben Wörter mit unterschiedlichen Schwellen. Darum muss jede erkannte Instanz ihre Definition und Quelle mitführen.
- Keine einzelne Kerze, Linie, Zone oder Indikatoranzeige beweist eine zukünftige Richtung. Technische Analyse ordnet historische Preis-, Zeit- und Volumendaten; sie erzeugt Hypothesen, keine Gewissheit. `[P02][Z01][Z02][Z03]`

## A. Was ein Markt ist und warum sich Preis bewegt

### A.1 Preis, Wert und Auktion

- **Preis** ist der Preis der letzten Ausführung oder eine daraus gebildete Referenz; **Bid** und **Ask** sind handelbare Angebote; **Mid** ist nur die Mitte beider Quotes. Keiner dieser Werte ist automatisch der „faire Wert“. Ein Chart zeigt ausgeführte Historie, nicht alle Absichten, stornierten Orders oder außerbörslichen Geschäfte. `[Z12][Z14][Z21]`
- Jeder ausgeführte Handel hat Käufer und Verkäufer. Die verkürzte Aussage „mehr Käufer als Verkäufer“ ist daher falsch. Richtungsdruck entsteht, wenn aggressive Marktteilnehmer verfügbare Gegenliquidität am Ask oder Bid verbrauchen, wenn passive Liquidität zurückgezogen/neu quotiert wird oder wenn neue Quotes auf anderen Preisen erscheinen. Delta/CVD versucht die **Aggressorseite** ausgeführter Trades zu messen, nicht die Gesamtzahl von Käufern und Verkäufern. `[Z12]`
- Ein Central-Limit-Order-Book ordnet Kauf- und Verkaufslimits nach Preis und innerhalb eines Preislevels nach der Venue-Priorität. Ein Market Buy handelt gegen den besten verfügbaren Ask; reicht dessen Größe nicht, entstehen Teilfüllungen über mehrere Preisstufen. Ein Limitauftrag kontrolliert den schlechtesten akzeptierten Preis, garantiert aber keine Ausführung. Ein Stop ist zunächst eine Triggerbedingung und wird erst danach zum Market- oder Limitauftrag. `[Z21]`
- Marktbewegung lässt sich als **Orderdruck relativ zur verfügbaren Liquidität** lesen. Dieselbe Kaufgröße kann in tiefer Liquidität fast keine Bewegung und in einem dünnen Buch einen Sprung erzeugen. Deshalb sind Volumen und Kursbewegung nicht austauschbar: hohes Volumen kann absorbiert werden, während geringes Volumen in einem Liquiditätsloch große Strecken zurücklegt. `[Z12][Z14]`
- Preisfindung ist eine fortlaufende Auktion: Der Markt erkundet Preise, akzeptiert manche Bereiche über Zeit/Volumen und verwirft andere schnell. Market Profile/TPO beschreibt Zeitakzeptanz; Volume Profile beschreibt ausgeführtes Volumen pro Preis; Orderbuchdaten beschreiben sichtbare, noch nicht ausgeführte Liquidität. Diese drei Ebenen dürfen nicht gleichgesetzt werden. `[Z05][Z13][Z14]`

### A.2 Kausalkette eines Moves

`Information oder Zwangsfluss → Änderung von Erwartungen/Risikolimits → Orders, Quote-Rückzug oder Hedging → Verhältnis von Aggression zu Gegenliquidität → Ausführungen/Slippage → sichtbare Preis- und Volumenstruktur → Reaktionen weiterer Teilnehmer`.

| Ursache | Übertragung auf Orders | Typischer Chartabdruck | Was nicht bewiesen ist |
|---|---|---|---|
| Neue Information | Erwartungen zu Cashflows, Zinsen, Risiko oder Angebot/Nachfrage werden neu bewertet | Gap, Displacement, Volatilitätssprung, neue Range | dass die erste Richtung bleibt oder die Nachricht allein kausal war |
| Positionierung/Hedging | Portfolios, Dealer oder Produzenten reduzieren/verschieben Risiko | beschleunigte Bewegungen an Schwellen, Laufzeit-/Basisänderungen | konkrete Identität eines Akteurs ohne Positionsdaten |
| Zwangsfluss | Stops, Margin Calls, Liquidationen, Mandats- oder Risikolimits lösen Orders aus | Kaskade, langer Docht oder schneller Durchlauf mehrerer Levels | dass jedes gebrochene Hoch „Stop Hunting“ ist |
| Liquiditätsrückzug | Market Maker/Limitgeber verbreitern Spread oder entfernen Tiefe | Slippage, Gaps, sprunghafte Ticks | dass großes sichtbares Limit sicher bestehen bleibt |
| Arbitrage/relative Bewertung | verbundene Instrumente werden gegeneinander gehandelt | Konvergenz von Spot/Future, Paaren oder Venues | risikolose Ausführung nach Kosten und Latenz |
| Technische/algorithmische Reaktion | viele Modelle beobachten ähnliche Hochs, VWAPs, Volatilitäts- oder Rebalancing-Schwellen | Cluster von Aktivität an gemeinsamen Referenzen | eine universelle geheime Institutionenregel |

### A.3 Reflexivität und Zeithorizonte

- Ein identischer Trade kann auf verschiedenen Horizonten verschiedene Bedeutungen haben: Scalper reagieren auf Queue/Spread, Daytrader auf Sessionstruktur, Swingtrader auf Tages-/Wochenstruktur, Asset Manager auf Cashflow-/Benchmarkrisiko und Hedger auf reale Exponierung. Ein 1-Minuten-Ausbruch kann gleichzeitig nur ein Docht im Tageschart sein. `[P02][P04][P10][P12][Z02]`
- Preisbewegung verändert selbst die Bedingungen: Gewinne/Verluste verändern Risikobudgets, Volatilität verändert Positionsgrößen, Breaks aktivieren Stops, Optionssensitivitäten verändern Hedges, und sichtbare Bewegungen ziehen Trendfolger oder Gegenparteien an. Daher sind Märkte rückgekoppelt; eine statische Korrelation ist keine Naturkonstante.
- **Akzeptanz** ist Aufenthalt/Handel jenseits eines Referenzbereichs; **Rejection** ist schnelle Rückkehr. Wie viel Zeit, Schlusskurse oder Volumen nötig sind, ist eine explizite Modellentscheidung und darf nicht nachträglich passend gemacht werden. `[Z02][Z14]`

## B. Teilnehmer, Motive und Informationsgrenzen

| Teilnehmer | Hauptmotiv | Typische Zwänge | Für den Chart relevant |
|---|---|---|---|
| Retail/aktive Trader | Spekulation, Hedging, Vermögensaufbau | Kapital, Gebühren, Hebel, Informations-/Latenznachteil | heterogene Stops und Markt-/Limitorders; keine einheitliche Gruppe |
| Market Maker/Liquiditätsanbieter | kontinuierlich quotieren, Spread/Fees verdienen, Bestand steuern | Inventar-, adverse-selection-, Kapital- und Venue-Risiko | Spread, Tiefe und Quote-Rückzug; nicht automatisch richtungsneutral in jedem Moment |
| Banken/Dealer | Kundenfluss vermitteln, bilanzieren, hedgen, strukturieren | Bilanz, Regulierung, Gegenpartei, Laufzeiten | OTC-/Derivatefluss und Hedges können Spot/Future beeinflussen |
| Asset Manager/Pensionsfonds/ETFs | Mandat, Benchmark, Allokation, Zu-/Abflüsse | Anlagegrenzen, Rebalancing, Liquidität | große, oft planbare Rebalances; nicht zwingend kurzfristige Kursprognose |
| Hedgefonds/Prop/CTA | relative oder absolute Rendite | Drawdown-/VaR-Limits, Finanzierung, Investorflüsse | diskretionäre, quantitative, Trend-, Mean-Reversion- und Arbitrageflüsse |
| Unternehmen/Produzenten/Importeure | reale Preis-, Zins- oder Währungsrisiken absichern | Geschäftsbedarf, Liefertermine, Accounting | Futures/Forwards können ohne spekulative Meinung gehandelt werden |
| Optionsdealer | Optionsbestand und Greeks hedgen | Delta/Gamma/Vega, Liquidität, Laufzeit | dynamische Hedges können Bewegung dämpfen oder verstärken; Vorzeichen hängt vom Bestand ab |
| Börsen/Clearing/Liquidationssysteme | Matching, Margin, Abwicklung, Ausfallschutz | Regelwerk, Initial-/Maintenance-Margin | Handelsunterbruch, Marginänderung, Mark-/Indexpreis und Liquidationen |

- Aus dem Chart allein kann normalerweise nicht sicher gelesen werden, **wer** gehandelt hat oder **warum**. Begriffe wie „Smart Money“, „Manipulation“ oder „Institutionenorder“ sind Hypothesen eines Frameworks. Beobachtbar sind Preis, Zeit, Volumen, Quotes und – falls vorhanden – venue-spezifische Derivat-/Orderflowdaten. `[P09][P10][P11][P12][P13][Z12]`
- Marktweite Aussagen benötigen mehrere Venues und Instrumente. Krypto-Open-Interest, Funding oder Liquidationen einer einzelnen Börse sind kein vollständiges globales Bild; Aktien-Volumen einer Venue kann Dark Pools/andere Handelsplätze auslassen; Spot-FX ist dezentral und Broker-Tickvolumen ist nicht das gesamte Marktvolumen.

## C. Handelsplätze, Ausführung und Orderarten

### C.1 Venue-Modelle und Mikrostruktur

| Modell | Funktionsprinzip | Analysegrenze |
|---|---|---|
| Börsliches Orderbuch | Orders werden nach Preis/Priorität gematcht; Trades und oft Markttiefe werden veröffentlicht | sichtbare Tiefe kann storniert, verborgen oder venue-lokal sein |
| Dealer/OTC | Kunde handelt gegen Dealer oder bilaterale Gegenpartei | Quotes und Volumen sind fragmentiert; Counterparty-/Settlement-Risiko |
| AMM/Pool | Preis folgt Poolbeständen/Formel; Arbitrage verbindet Pool mit anderen Venues | Slippage hängt von Pooltiefe ab; Impermanent Loss und Smart-Contract-Risiko |
| Opening/Closing Auction | Orders werden gesammelt und zu einem Auktionspreis gematcht | anderes Verhalten als kontinuierlicher Handel; Imbalances können hohe Aktivität erzeugen |

- **Tick Size** ist kleinste Preisstufe, **Lot/Contract Size** die handelbare Mengeneinheit, **Multiplier** übersetzt einen Punkt in Geld, **Notional** ist Preis × Menge × Multiplikator. P&L, Stopdistanz und Positionsgröße müssen auf diesen Spezifikationen beruhen, nicht nur auf sichtbaren Chartpunkten.
- **Spread** ist Ask minus Bid. **Slippage** ist Differenz zwischen erwarteter und tatsächlicher Ausführung. **Market Impact** ist die eigene Preiswirkung. **Adverse Selection** bedeutet, dass passive Liquidität bevorzugt kurz vor ungünstiger Bewegung ausgeführt wird. Gebühren, Rebates, Finanzierung, Borrow, Wechselkurs und Steuer-/Abwicklungsregeln gehören zur Nettobetrachtung.
- Ein Candle-Backtest, der innerhalb einer OHLC-Bar zugleich Entry, Stop und Target berührt, kennt die Reihenfolge ohne feinere Daten nicht. Realistische Simulation braucht Bid/Ask, Latenz, Queue-/Fill-Annahme, Teilfüllungen, Handelsunterbrüche und Gaplogik.

### C.2 Ordermatrix

| Order | Was kontrolliert sie? | Hauptgefahr/Fehlannahme |
|---|---|---|
| Market | sofortige Ausführungspriorität | Preis nicht garantiert; Spread, Slippage und Teilfüllungen `[Z21]` |
| Limit | schlechtester akzeptierter Kauf-/Verkaufspreis | keine Ausführungsgarantie; Queue-Position und adverse selection `[Z21]` |
| Stop-Market | Trigger, danach Marketorder | Gaps/Illiquidität können weit vom Trigger füllen `[Z21]` |
| Stop-Limit | Trigger plus Preisgrenze | kann nach Trigger ungefüllt bleiben `[Z21]` |
| Trailing Stop | Trigger folgt Preis nach definierter Distanz | Distanz kann Volatilität ignorieren; Brokerdefinition prüfen |
| Bracket/OCO | verknüpft Entry, Stop und Target; eine Ausführung storniert die andere | Race Conditions, Teilfüllungen und Venue-Unterstützung prüfen |
| IOC/FOK | sofortige Teilfüllung/Storno bzw. vollständige Sofortfüllung | kann in dünnen Büchern kaum oder gar nicht füllen |
| Post-only | soll nur als Maker ins Buch | wird storniert/abgewiesen, wenn sie sofort matchen würde |
| Reduce-only | darf bestehende Position nur reduzieren | Schutz hängt von Börsenimplementierung und Positionsmodus ab |
| GTC/DAY/GTD | zeitliche Gültigkeit | Sessionende, Zeitzone und Corporate-/Contract-Events beachten |

## D. Instrumente und ihre eigene Mechanik

| Instrument | Ökonomischer Kern | Besondere Daten/Risiken |
|---|---|---|
| Aktie | Anteil am Unternehmen; Preis reflektiert erwartete Cashflows/Risiko und Flow | Earnings, Guidance, Dividende, Splits, Buybacks, Verwässerung, Borrow/Short Squeeze, Handelszeiten |
| ETF/Indexprodukt | Korb/Regelwerk; Creation/Redemption verbindet Produkt und Underlyings | Tracking Error, Rebalance, Gewichtung, Premium/Discount, gehebelter täglicher Reset |
| Anleihe/Zinsfuture | vertragliche Cashflows bzw. Zins-/Durationsexposure | Rendite bewegt sich invers zum Preis; Duration, Kredit-, Kurven- und Convexity-Risiko |
| Spot-FX/Forward | Austausch zweier Währungen | Zinsdifferenz, Carry/Swap, dezentrale Liquidität, Zentralbank-/Länderrisiko `[Z27]` |
| Rohstoff | Anspruch auf/Referenz zu physischem Gut | Lagerung, Transport, Saison, Qualität, Standort, Convenience Yield, Terminkurve `[Z23]` |
| Future | standardisierter befristeter Derivatvertrag | Verfall, Cash/Physical Settlement, Initial-/Maintenance-Margin, Roll, Basis `[Z22][Z23]` |
| Perpetual | unbefristetes Krypto-Derivat | Funding, Mark-/Indexpreis, Liquidation, Börsen-/Counterparty-Risiko `[Z15][Z20]` |
| Option | asymmetrischer Anspruch auf Kauf/Verkauf bis/zu Verfall | Strike, Laufzeit, IV, Delta/Gamma/Theta/Vega, Pin-/Assignmentrisiko `[Z24][Z25]` |
| CFD/Leveraged OTC | Vertrag mit Broker auf Kursdifferenz | keine Eigentümerschaft, Finanzierung, Spread, Broker-/Gegenparteirisiko |

### D.1 Futures, Basis und Terminkurve

- **Basis** ist die Differenz zwischen Future und Spot/Referenz. Vor Verfall reflektiert sie u. a. Finanzierung, Lagerung, erwartete Dividenden/Erträge, Convenience Yield und Knappheit; zum Verfall konvergieren Future und lieferbarer/abrechenbarer Referenzpreis nach Vertragsmechanik. `[Z22][Z23]`
- **Contango**: spätere Futures liegen höher als Spot/nahe Laufzeiten; **Backwardation**: spätere Futures liegen tiefer. Das ist keine automatische Long-/Short-Regel. Rollrendite entsteht beim Wechsel der Laufzeit und ist von Spotrendite zu trennen. `[Z23]`
- Margin ist Sicherheitsleistung, nicht Kaufpreis. Hebel vergrößert Exposure relativ zum gebundenen Kapital; er schafft keinen Edge. Initial Margin eröffnet, Maintenance Margin begrenzt laufende Verluste; Margin Call/Liquidation kann erzwungene Orders erzeugen. `[Z22][Z20]`

### D.2 Optionen und Volatilität

- Optionswert besteht aus innerem und Zeitwert. **Implied Volatility (IV)** ist die im Marktpreis enthaltene Volatilitätsannahme des Bewertungsmodells; sie ist weder Richtungssignal noch Garantie realisierter Volatilität. Nach bekannten Events kann IV stark fallen („IV crush“), selbst wenn der Underlying-Preis bewegt ist. `[Z25]`
- **Delta** misst lokale Preisempfindlichkeit und wird auch als Hedgegröße verwendet; **Gamma** misst Deltaänderung; **Theta** den modellierten Zeitwertverlust; **Vega** die Empfindlichkeit gegenüber IV. Greeks ändern sich mit Preis, Zeit und IV und sind keine konstanten Kennzahlen. `[Z24]`
- Optionshedging kann den Underlying-Flow beeinflussen, aber ohne Kenntnis der Dealer-Nettoposition ist „positive/negative Gamma“-Wirkung nicht sicher bestimmbar. Open Interest zeigt offene Kontrakte, nicht eindeutig Long-/Short-Richtung oder Motivation.

## E. Warum und wann Volatilität entsteht

| Zeit/Ereignis | Mechanismus | Professionelle Prüfvariablen |
|---|---|---|
| Session-Open/Close/Auktion | neuer Informationsstand, Overnight-Inventar, Benchmark-/Closing-Flows | Spread, Gap, Opening Range, Auktionsimbalance, Sessionzeitzone |
| London-/New-York-Überlappung | mehrere Liquiditätspools/Teilnehmer gleichzeitig aktiv | instrumentspezifisches Volumen und typische, nicht garantierte Aktivitätsfenster |
| Makrodaten | Actual, Forecast, Previous und Revision verändern Erwartungen | Überraschungsgröße relativ zum Konsens, Details, Vorpositionierung, erste Reaktion vs. Akzeptanz `[Z10][Z11]` |
| Zentralbank | aktueller Satz plus Pfad, Sprache, Bilanz/Liquidität | Statement, Projektionen, Pressekonferenz, Marktpricing vor dem Event |
| Earnings/Guidance | erwartete Cashflows und Unsicherheit werden neu bewertet | Ergebnis vs. Konsens, Umsatz/Marge, Ausblick, Positionierung, IV `[Z25]` |
| Verfall/Rebalance | Derivate laufen aus, Benchmarks/Gewichte werden angepasst, Hedges rollen | Laufzeit, Open Interest, Closing Auction, Basis/Terminkurve |
| Margin/Liquidation | Markpreis unterschreitet Risikoschwelle, Position wird zwangsreduziert | Mark- vs. Last-Price, Maintenance Margin, OI, Funding, Liquidationsdaten `[Z15][Z20]` |
| Dünne Liquidität/Feiertag | weniger Gegenorders; einzelne Orders bewegen mehr | Spread/Tiefe, Handelskalender, Venue, Wochenende/Overnight |

- Volatilität misst Schwankungsbreite, nicht Richtung. Sie clustert häufig: volatile Phasen folgen eher volatilen, ruhige eher ruhigen; dennoch ist ein Ausbruch aus Kompression nicht in Richtung oder Größe sicher. ATR, Bollinger-Bandbreite, historische und implizite Volatilität messen unterschiedliche Dinge. `[Z03][Z17][Z25]`
- Eine Nachricht wirkt nicht durch das Etikett „gut/schlecht“, sondern relativ zu Erwartungen, Positionierung und dem dominanten Bewertungsfaktor. Gute Wachstumsdaten können Aktien stützen oder über höhere Zinserwartungen belasten; höhere Zinsen können eine Währung stützen, wenn die Differenz unerwartet wächst, aber Risiko-/Rezessions- oder Interventionseffekte können dominieren. DXY-, Yield-, Gold- oder Aktienkorrelationen sind deshalb bedingt, nicht strikt. `[Z10][Z11][Z26][Z27]`
- Relevante Makrokanäle: Leitzins/erwarteter Pfad → Geldmarktsätze/Discount Rate; Inflation → reale Kaufkraft/Zinserwartung; Wachstum/Arbeitsmarkt → Cashflow- und Politikpfad; Kreditspreads → Finanzierung/Risiko; Liquidität/Bilanzpolitik → verfügbare Finanzierung; Wechselkurs → Importpreise, Auslandserträge und Kapitalflüsse. Diese Kanäle können gleichzeitig gegeneinander wirken.

## F. Short Selling, Leverage, Finanzierung und Zwangsrisiken

- Beim **Short** wird ein geliehenes oder synthetisch abgebildetes Instrument verkauft und später zurückgekauft. Maximalgewinn eines ungehebelten Aktien-Shorts ist bei Preis null begrenzt, theoretischer Verlust bei steigendem Preis unbegrenzt. Hinzu kommen Borrow Fee, mögliche Rückrufbarkeit, Dividendenersatz, Margin und Gaprisiko. Futures/Perpetual-Shorts sind Derivatpositionen und folgen ihrer Margin-/Fundingmechanik.
- **Short Interest** ist Bestandsgröße, **Days to Cover** setzt sie ins Verhältnis zu durchschnittlichem Volumen, **Borrow Rate** zeigt Leihknappheit, und ein **Short Squeeze** ist beschleunigtes Eindecken. Keine dieser Größen allein sagt Zeitpunkt oder Richtung sicher voraus.
- Leverage ändert bei gleicher Positionsgröße nicht den Marktmove, aber das gebundene Kapital und die Distanz zur Margin-/Liquidationsschwelle. Professionelle Risikomessung basiert auf Geldrisiko, Notional, Stop-/Gap-Szenario und Korrelation – nicht auf dem Hebelknopf allein. `[Z20]`
- Funding bei Perpetuals überträgt periodisch Zahlungen zwischen Longs und Shorts, um den Kontrakt an den Index zu binden. Positives Funding bedeutet typischerweise Longs zahlen Shorts, negatives umgekehrt; es ist Positionierungs-/Kostenkontext, kein eigenständiges Umkehrsignal. `[Z15]`

## G. Risiko, Erwartungswert und Überlebensfähigkeit

- Ein positiver Prozess benötigt keinen hohen Winrate-Wert. Brutto-Erwartungswert pro Trade: `E = p(Gewinn) × Durchschnittsgewinn − p(Verlust) × Durchschnittsverlust`; netto werden Gebühren, Spread, Slippage, Finanzierung und sonstige Kosten abgezogen. Sechs Trades mit drei Verlusten von je CHF 100 und drei Gewinnen von je CHF 200 ergeben `−300 + 600 = +300` vor Kosten. Die Reihenfolge verändert Drawdown und Kapitalbedarf, nicht den arithmetischen Bruttosaldo.
- `R` ist das anfänglich definierte Geldrisiko. Positionsgröße in der einfachsten linearen Form: `zulässiges Geldrisiko ÷ (Stopdistanz × Geldwert je Preiseinheit)`, anschließend angepasst an Lot/Contract, Gebühren, Slippage und mögliche Gaps. Ein enger Stop erlaubt rechnerisch größere Größe, macht das Gap-/Slippage- oder normale-Rausch-Risiko aber nicht kleiner.
- **Drawdown** wird vom bisherigen Equity-Hoch gemessen. Nach 10 % Verlust sind 11,1 % Gewinn zur Erholung nötig; nach 50 % Verlust 100 %. Risk of Ruin steigt mit negativem/unsicherem Edge, großer Einsatzfraktion, Korrelation und schweren Verlustschwänzen. Keine Positionsformel repariert einen nicht validierten Edge.
- Portfolio-Risiko ist nicht die Summe isolierter Stops: korrelierte Aktien, mehrere USD-Paare oder Krypto-Assets können dieselbe Faktorwette bilden. Zu prüfen sind Brutto-/Nettoexposure, Sektor-/Währungs-/Duration-/Beta-/Volatilitätsfaktoren, offene Gaps und gemeinsame Eventrisiken.
- Ein Stop ist eine Invalidierungs-/Risikotransferregel, keine Ausführungsgarantie. Ein Take Profit realisiert ein definiertes Ziel, kann aber positive Ausreißer abschneiden. Break-even- oder Trailing-Regeln verändern die komplette Renditeverteilung und müssen zusammen mit Entry/Exit getestet werden, nicht als kostenlose Verbesserung.

## H. Forschung, Backtest, Datenqualität und professionelle Lernschleife

| Phase | Pflicht | Typische Täuschung |
|---|---|---|
| Hypothese | Beobachtung, Ursache/Proxy, exakte Definition, Markt/Timeframe, erwartete Bedingung | nachträglich Muster benennen |
| Datensatz | Quelle, Venue, Zeitzone, Corporate Actions, Kontrakt-Roll, Delistings, Bid/Ask | Survivorship-, Look-ahead- und fehlerhafte Backadjustment-Daten |
| Signalbau | nur Informationen verwenden, die zu diesem Zeitpunkt verfügbar waren | Pivot erst später bestätigt, revidierte Makrodaten, Intrabar-Reihenfolge |
| Simulation | Kosten, Spread, Slippage, Latenz, Queue, Teilfüllungen, Gaps, Handelszeiten | Füllung am Kerzenextrem ohne handelbaren Preis |
| Stichprobe | In-Sample, Validation, unangetastetes Out-of-Sample; Marktregime trennen | Parameter auf Gesamtverlauf optimieren |
| Robustheit | Parameterumgebung, andere Perioden/Märkte, Walk-forward, Monte-Carlo/Bootstrap | bestes Ergebnis aus vielen Tests ohne Multiple-Testing-Korrektur |
| Forward-Test | Paper und anschließend kleinste realistische Größe | Paper-Fills mit Live-Ausführung gleichsetzen |
| Journal/Review | Screenshot, Kontext, Regelversion, geplantes/realisiertes Risiko, Ausführung, Abweichung | Gewinner als gute und Verlierer als schlechte Entscheidung werten |

- Wichtige Biases: **Survivorship** (nur Überlebende), **look-ahead** (Zukunftsdaten), **selection/data snooping** (viele Varianten, nur Sieger berichtet), **overfitting**, **regime bias**, **publication bias** und **outcome bias**. Ein beeindruckender Backtest ohne Daten-/Versions-/Kostenprotokoll ist kein reproduzierbarer Nachweis.
- Kennzahlen gemeinsam lesen: Zahl unabhängiger Trades, Nettoerwartung, Trefferquote, durchschnittlicher Gewinn/Verlust, Profit Factor, Maximum/Duration Drawdown, Volatilität der Returns, Tail Loss, Exposure, Turnover und Kostenanteil. Sharpe/Sortino und ähnliche Quotienten hängen von Annahmen, Stichprobe und Skalierung ab und ersetzen keine Verteilungsanalyse.
- Psychologische Fehler sind oft Prozessfehler: FOMO, Revenge Trading, Verlustaversion, Recency, Anchoring, Overconfidence, Bestätigungs- und Outcome Bias. Gegenmaßnahmen sind vorab definierte Beobachtungs-/Invalidierungskriterien, Größenlimits, Pausenregeln, Checklisten und ein Journal; sie erzeugen keinen Edge, verhindern aber Regelbruch.
- **Professionelle Lernschleife:** Daten erfassen → Hypothese formulieren → Definition einfrieren → testen → Gegenbeispiele suchen → OOS/Forward prüfen → kleine Live-Ausführung messen → Regel versionieren oder verwerfen. Nie wird ein Verlust nachträglich durch eine neue, vorher nicht definierte Ausnahme „erklärt“.

## I. Analysehierarchie für ein Obsidian-Gehirn

1. **Instrumentvertrag:** Was wird rechtlich/ökonomisch gehandelt, auf welcher Venue, mit welchem Tick, Multiplikator, Settlement, Verfall, Funding/Borrow und Handelskalender?
2. **Datenzustand:** Welche Quelle, Latenz, Zeitzone, Adjustierung, Session und Granularität liegen vor; fehlen Trades, Quotes, andere Venues oder Revisionen?
3. **Regime:** Trend, Balance, Übergang; Volatilität, Liquidität und Korrelation; HTF und LTF getrennt.
4. **Auktions-/Strukturkarte:** Swings, S/R, Supply/Demand, Profile, Gaps, FVGs, Liquidität und offene Ziele – jeweils Definition/Quelle speichern.
5. **Katalysatoren/Flows:** Kalender, News, Earnings, Auktion, Verfall, Funding, Margin, Rebalance; bekannte Information von bloßer Story trennen.
6. **Triggerbeobachtung:** Break, Akzeptanz, Rejection, Sweep, Displacement, Orderflow – niemals vor Kerzenschluss oder Datenbestätigung rückwirkend umetikettieren.
7. **Gegenevidenz:** Was müsste sichtbar sein, damit die Hypothese falsch oder nicht handelbar ist? Welche alternative Erklärung passt ebenfalls?
8. **Risiko/Ausführung:** Geldrisiko, Notional, Korrelation, Stop-/Gap-/Slippage-Szenario, Orderspezifikation, Gebühren und technische Ausfallwege.
9. **Nachkontrolle:** Planqualität getrennt vom Ergebnis bewerten, Daten und Screenshot speichern, Regelversion und Abweichungen protokollieren.

## J. Marktübergreifende Beziehungen und Übertragungskanäle

- **Zinsen und Anleihen:** Steigt die geforderte Rendite, fällt bei sonst gleichen Bedingungen der Preis einer bestehenden Festzinsanleihe. Längere Duration reagiert stärker auf Renditeänderungen. Aktienbewertung kann über höhere Diskontsätze belastet werden, doch Gewinnwachstum, Inflation, Risikoprämie und Positionierung können den Effekt überlagern. Deshalb ist „Yield hoch = Aktien runter“ nur eine bedingte Hypothese.
- **Währungen:** Ein FX-Kurs bewertet eine Währung relativ zu einer anderen. Relevant sind nicht nur heimische Daten, sondern die Differenz der erwarteten Zins-, Inflations-, Wachstums- und Risikopfade beider Länder. Carry erhält die Zinsdifferenz, trägt aber Wechselkurs-, Liquiditäts- und Crowdingrisiko. `[Z27]`
- **Dollar und globale Assets:** Ein Dollarindex ist ein gewichteter Währungskorb und nicht „der Dollar gegen alles“. Dollar, Gold, Rohstoffe und Emerging Markets zeigen häufig Beziehungen über Finanzierung, Preisnotierung und Risikoappetit, aber keine unveränderliche inverse Korrelation. `[Z26]`
- **Rohstoffe:** Spot-, Frontmonat- und länger laufender Future sind unterschiedliche Preise. Inventar, Produktion, Wetter, Geopolitik, Qualität, Transport und Convenience Yield wirken auf die Kurve; ein Spot-Chart allein erklärt Rollkosten eines Futures-/ETF-Produkts nicht. `[Z23]`
- **Indizes und Einzeltitel:** Ein kapitalisierungsgewichteter Index kann von wenigen großen Komponenten bewegt werden. Marktbreite, Sektorrotation und gleichgewichtete Varianten helfen zu unterscheiden, ob ein Move breit oder konzentriert ist; sie sind Kontext, kein automatisches Reversalsignal.
- **Korrelation und Beta:** Korrelation misst gemeinsame standardisierte Bewegung in einem Fenster, Beta relative Sensitivität zu einer Benchmark. Beide ändern sich mit Zeitraum und Regime, sagen keine Kausalität und können in Stressphasen zusammenlaufen. Hedge-Verhältnisse benötigen deshalb aktuelle Exposures und Stressszenarien.

## K. Nicht-charttechnische Ereignisse, Datenbrüche und operative Risiken

- Aktiencharts müssen Splits, Sonderdividenden, Rechte, Spin-offs, Fusionen, Delistings und Handelsunterbrüche korrekt behandeln. Adjusted OHLC ist für Renditehistorie hilfreich, kann aber historische handelbare Preise verändern; Roh- und adjustierte Daten mit klarer Methode getrennt speichern.
- Futures benötigen Kontraktidentität und Rollmethode. Ein Continuous Contract kann Sprünge entfernen oder Renditen verzerren; Back-/Ratio-Adjustment ist Analysekonvention, kein historisch handelbarer Einzelkontrakt. `[Z22][Z23]`
- Makrodaten werden revidiert. Ein Backtest darf nicht den heute bekannten revidierten Wert so verwenden, als sei er bei der Erstveröffentlichung bekannt gewesen. Kalenderzeit, Release-Vintage und Zeitzone gehören in das Eventobjekt. `[Z10][Z11]`
- Krypto handelt rund um die Uhr, doch Wartungen, Oracle-/Indexausfälle, Depegs, Chain Congestion, Exchange Insolvency und unterschiedliche Markpreise sind eigenständige Risiken. Ein Liquidationslevel hängt von Börse, Marginmodus, Gebühren und Markpreisformel ab. `[Z15][Z20]`
- Plattformausfall, Internet-/Stromausfall, API-Duplikat, falsche Positionsseite, Zeitzonen-/DST-Fehler, stale Quote und nicht synchronisierte Uhr sind reale Ausführungsrisiken. Schutzobjekte: eindeutige Order-ID, Idempotenz, Positionsabgleich, Kill Switch, maximale Notional-/Orderrate und unabhängiger Broker-/Venue-Check.
- Spoofing, Layering, Wash Trading und Pump-and-Dump sind mögliche missbräuchliche Praktiken; ein einzelnes verschwundenes Limit oder ein langer Docht beweist sie nicht. Sichtbare Orderbuchliquidität ist Absicht bis zur Ausführung und kann legitim storniert werden. Regulatorische und venue-spezifische Definitionen müssen separat geprüft werden.

## L. Kompaktglossar der professionellen Grundbegriffe

| Begriff | Präzise Kurzdefinition |
|---|---|
| Ask/Offer | niedrigster aktuell angebotener Verkaufspreis auf der betrachteten Venue |
| Bid | höchster aktuell angebotener Kaufpreis auf der betrachteten Venue |
| Spread | Ask minus Bid; unmittelbarer Reibungsanteil einer Hin-und-zurück-Ausführung |
| Depth | sichtbare Quotegrößen über mehrere Preisstufen; nicht gleich garantiert verfügbarer Fill |
| Liquidity | Fähigkeit, Größe zeitnah mit geringer Preiswirkung zu handeln; umfasst Spread, Tiefe und Erneuerung |
| Volatility | Größe/Streuung von Preisänderungen; sagt allein keine Richtung |
| Volume | ausgeführte Menge in definierter Venue/Periode, nicht offene Auftragsmenge |
| Orderflow | Abfolge/Klassifikation ausgeführter und teils quotierter Orders; feed- und venueabhängig |
| Slippage | Differenz zwischen erwartetem und realisiertem Ausführungspreis |
| Gap | Preisbereich zwischen Referenzkursen ohne bzw. mit wenig Handel in der betrachteten Darstellung |
| Return | relative Preis-/Total-Return-Veränderung über ein definiertes Intervall |
| Notional | wirtschaftlicher Positionswert vor Berücksichtigung der hinterlegten Margin |
| Margin | hinterlegte Sicherheit zur Deckung eines gehebelten Kontraktrisikos |
| Leverage | Exposure relativ zu Kapital/Margin; vervielfacht Wirkung, nicht Vorhersagequalität |
| Mark Price | von der Venue berechnete faire Referenz für P&L/Liquidation; nicht zwingend letzter Trade |
| Index Price | externe/zusammengesetzte Spotreferenz eines Derivats |
| Basis | Differenz zwischen Derivat-/Futurepreis und Spot-/Referenzpreis |
| Carry | Halteertrag/-kosten aus Zins, Funding, Dividende, Lagerung, Borrow oder Convenience Yield |
| Open Interest | offene, noch nicht glattgestellte Derivatekontrakte/Positionseinheiten |
| Expiry | Zeitpunkt, an dem ein befristeter Vertrag ausläuft/abgerechnet wird |
| Roll | Schließen/Übertragen aus einer Laufzeit in eine spätere |
| Settlement | finanzielle oder physische Erfüllung eines Geschäfts/Derivats |
| Drawdown | Rückgang vom bisherigen Equity-Hoch zum späteren Tief/aktuellen Wert |
| MAE/MFE | größte ungünstige/günstige Bewegung während eines Trades |
| Expectancy | durchschnittlich erwarteter Nettoertrag pro Versuch unter der geschätzten Verteilung |
| Tail Risk | seltene, extreme Verluste außerhalb typischer Schwankung |
| Regime | Zustand aus Trend/Balance, Volatilität, Liquidität, Korrelation und Makroumfeld |
| Acceptance | anhaltender Handel/Zeit/Volumen jenseits einer Referenz nach definierter Schwelle |
| Rejection | fehlende Akzeptanz und schnelle Rückkehr aus einem getesteten Preisbereich |
| Absorption | große aggressive Ausführung mit wenig Preisfortschritt; Gegenliquidität nimmt Flow auf |
| Exhaustion | nachlassender Fortschritt/Teilnahme eines Moves; erst über definierte Daten feststellbar |
| Confluence | mehrere möglichst unabhängige Informationsfamilien stützen dieselbe Hypothese |
| Invalidation | vorab definierte Beobachtung, die eine Hypothese aufhebt; nicht identisch mit garantiertem Fill |

## 1. Datenfundament und Objektmodell
### 1.1 Primäre Marktdaten

| Objekt | Bedeutung | Pflichtfelder | Nicht automatisch ableiten |
|---|---|---|---|
| Tick/Trade | tatsächlich ausgeführter Handel | Zeit, Preis, Größe; bei Orderflow zusätzlich Aggressor-Seite | Absicht des Teilnehmers |
| Quote | aktuell sichtbares Gebot/Angebot | Zeit, Bid, Ask, Größen | Ausführung oder dauerhafte Liquidität |
| OHLCV-Bar | Verdichtung eines Zeitintervalls | Open, High, Low, Close, Volumen, Start/Ende, Zeitzone | Reihenfolge der Bewegungen innerhalb der Bar |
| Session | zeitlich abgegrenzter Handelsabschnitt | Markt, Zeitzone, Start, Ende, Feiertagsstatus | gleiche Liquidität an jedem Tag |
| Derivatdaten | Positionierungs-/Hebelkontext | Open Interest, Funding, Liquidationen, Basis, Börse | sichere Richtung des nächsten Moves |
| Wirtschaftsevent | geplanter Informationsimpuls | Zeit, Währung/Markt, Wichtigkeit, Actual, Forecast, Previous, Revision | lineare Reaktion „gute Zahl = Kurs steigt“ |

### 1.2 Charttypen
- **Candlestick:** zeigt OHLC pro Intervall; Körper beschreibt Open–Close, Dochte die Extrempreise. Ein langer Docht ist zunächst nur Ablehnung/Zurücknahme innerhalb der Bar, nicht von allein eine Umkehr. `[P02][P03][Z01][Z02]`
- **Bar-Chart:** enthält dieselben OHLC-Informationen in anderer Darstellung. `[Z02]`
- **Linienchart:** reduziert typischerweise auf Schlusskurse; nützlich für grobe Struktur, blendet Intrabar-Extrema aus. `[Z02]`
- **Volume Profile:** ordnet Volumen **Preisniveaus** statt nur Zeitbalken zu. `[Z05][Z13]`
- **Market Profile/TPO:** ordnet Zeit bzw. TPO-Buchstaben Preisniveaus zu; POC, Value Area und Initial Balance beschreiben die Auktion, nicht dasselbe wie echtes Volumen. `[Z14]`
- **Footprint:** zerlegt eine Bar nach Preislevel und Bid-/Ask-Ausführungen; dafür ist geeignete Orderflow-Datenqualität nötig. `[Z12]`

### 1.3 Timeframe-Regel
- Ein Muster gehört immer zu einem **Timeframe**. Ein 5-Minuten-Hoch kann innerhalb einer 1-Stunden-Kerze nur internes Rauschen sein. `[P02][P04][P10][P12][Z02]`
- Höhere Timeframes dienen in den Videos primär der Regime-, Struktur- und Zonenbestimmung; niedrigere Timeframes der Verfeinerung und Bestätigung. `[P04][P10][P12][Z02]`
- Der Analyzer speichert deshalb für jedes Objekt: `timeframe`, `parent_timeframe`, `session`, `bar_close_confirmed`, `source_definition`.

## 2. Marktstruktur
### 2.1 Swingpunkte

- **Swing High:** lokales Hoch, umgeben von niedrigeren Hochs. **Swing Low:** lokales Tief, umgeben von höheren Tiefs. Die Zahl der Vergleichsbalken ist eine Konfiguration und muss gespeichert werden. `[P02][P05][P10][P12]`
- Swingpunkte sind gleichzeitig Strukturanker, mögliche Support-/Resistance-Bereiche und sichtbare Liquiditätsreferenzen. `[P05][P10][P12]`
- Ein noch nicht abgeschlossener Pivot darf nicht als bestätigter Swing gespeichert werden; sonst entsteht Look-ahead-Bias.

### 2.2 Regime
| Regime | Erkennungsprinzip | Unsicherheit/Gegenbeispiel |
|---|---|---|
| Aufwärtstrend | Folge höherer Hochs und höherer Tiefs | einzelne tiefere Kerze ist noch kein bestätigter Trendwechsel |
| Abwärtstrend | Folge tieferer Tiefs und tieferer Hochs | ein starkes bullisches Retracement kann nur Korrektur sein |
| Range/Balance | Preis rotiert zwischen wiederholt respektierten Grenzen; keine saubere HH/HL- oder LL/LH-Folge | eine Range kann auf dem LTF Trend und auf dem HTF nur eine Pause sein |
| Übergang | bisherige Sequenz wird verletzt, neue Gegensequenz ist noch nicht etabliert | CHoCH/MSS ist je nach Creator früher oder später bestätigt |

Quellen: `[P02][P05][P10][P12][Z01][Z02]`.

### 2.3 Impuls, Korrektur, Displacement
- **Impuls/Expansion:** relativ direktionale Bewegung mit größeren Körpern, wenig Überlappung und strukturellem Fortschritt. `[P05][P08][P09][P10][P13]`
- **Korrektur/Pullback:** Gegenbewegung innerhalb eines übergeordneten Legs; häufig mehr Überlappung und weniger struktureller Fortschritt. `[P02][P05][P10][Z02]`
- **Displacement:** im SMC-Kontext kräftige Expansion, die häufig Struktur bricht und ein Ungleichgewicht/FVG hinterlässt. Das FVG beweist nicht, wer gehandelt hat. `[P09][P10][P11][P13]`
- Messbare Merkmale: Body/Range-Verhältnis, Range relativ zu ATR, Überlappungsquote, Zahl gebrochener Swings, Volumen relativ zur Historie. Nur die ersten vier stammen als Prinzip aus den ausgewerteten Preisaktionsvideos; Volumen ist eine alternative Creator-Schule. `[P08][Z02]`

### 2.4 BOS, CHoCH und MSS
| Begriff | Kernidee | Mindestdaten | Varianten |
|---|---|---|---|
| BOS | Bruch eines relevanten Strukturpunkts, oft als Fortsetzung gelesen | Swing-Level, Break-Seite, Wick/Close, Timeframe | manche Creator akzeptieren Wick; andere verlangen Schlusskurs/Displacement |
| CHoCH | erster Bruch gegen die bisherige Strukturfolge | vorheriges Regime, geschütztes Hoch/Tief, Bruch | frühes Warnsignal versus bestätigte Umkehr |
| MSS | Strukturverschiebung; häufig Sweep + Displacement + Gegenbruch | Liquiditätsereignis, Impuls, gebrochener Pivot | teils Synonym für CHoCH, teils strengere Untermenge |

- Der Analyzer darf `BOS`, `CHoCH` und `MSS` nicht allein anhand eines Linienkreuzes etikettieren. Er muss `definition_variant`, `reference_swing`, `break_method`, `close_confirmed`, `displacement_present` speichern. `[P09][P10][P11][P12][P13]`
- Ein BOS in eine HTF-Zone hinein kann Fortsetzung im LTF, aber Zielerreichung/Überdehnung im HTF bedeuten. `[P04][P10][P12]`

## 3. Support, Resistance, Supply und Demand
### 3.1 Support und Resistance

- **Support:** Bereich, an dem Preis zuvor nach oben reagierte; **Resistance:** Bereich, an dem Preis zuvor nach unten reagierte. Als **Zone**, nicht als mathematisch exakte Linie behandeln. `[P04][Z01][Z02]`
- Zeichnungsquellen: markante Swing-Hochs/-Tiefs, mehrfache Reaktionen, Rollenwechsel und höhere Timeframes. `[P04][Z02]`
- **Rollenwechsel:** gebrochener Support kann bei Rücklauf Resistance werden; gebrochene Resistance kann Support werden. Das ist eine mögliche Marktreaktion, kein Automatismus. `[P04][Z02]`
- Zu viele Linien erzeugen widersprüchliche Signale. `[Z01][Z02]`
- Zonenfelder: `upper`, `lower`, `origin_timeframe`, `touch_count`, `last_touch`, `close_through_count`, `freshness`, `role`, `invalidated`.

### 3.2 Supply und Demand
- **Demand-Zone:** Basis vor einer klaren Aufwärtsbewegung; **Supply-Zone:** Basis vor einer klaren Abwärtsbewegung. `[P09]`
- Aus dem ausgewerteten Video stammen als Qualitätsmerkmale: starker Abgang, sichtbarer Strukturbruch, FVG/Imbalance und möglichst frischer erster Rücklauf. `[P09]`
- Eine Zone wird durch wiederholte Tests nicht automatisch „stärker“: `[P09]` bevorzugt Frische, während klassische S/R-Lehre wiederholte Reaktionen zur Sichtbarkeit eines Levels nutzt. Das sind zwei unterschiedliche Modelle, die getrennt bleiben müssen.
- **Invalidierung:** nachhaltige Akzeptanz/Schlusskurse durch die gegenüberliegende Zonengrenze; die genaue Wick-/Close-Regel ist quellenabhängig. `[P09]`

### 3.3 Order Block
- In `[P11]` ist ein Order Block die letzte Gegenkerze bzw. kleine Basis vor einem impulsiven Move, der Liquidität nimmt, ein FVG erzeugt und Struktur verändert. `[P12]` ergänzt Inducement als Auswahlfilter.
- Bullish: letzte bearishe Kerze/Basis vor bullischem Displacement; bearish invers. Die Zone kann Körper, gesamte Kerze oder ausgewählten Bereich umfassen – Creator definieren das unterschiedlich.
- Erforderliche Felder: `direction`, `origin_candle`, `zone_method`, `sweep_present`, `fvg_present`, `structure_shift`, `inducement`, `mitigation_count`, `invalidated`.
- Nicht jede letzte Gegenkerze ist ein Order Block. Ohne definierte Folgebewegung und Strukturbezug ist sie nur eine Kerze. `[P11][P12]`

### 3.4 Breaker, Mitigation und Rejection Block
- **Breaker Block:** ehemaliger Order Block, der versagt und nach Strukturwechsel als Bereich auf der Gegenseite betrachtet wird. Die Primärplaylist definiert ihn nicht vollständig; deshalb nur als Begriffsrelation speichern, nicht automatisch handeln. `[P10–P12]`
- **Mitigation:** Rückkehr in einen zuvor markierten Block/eine Ineffizienz. Ein Touch beweist weder vollständige „Abarbeitung“ noch Reversal.
- **Rejection Block:** Docht-/Ablehnungsbereich nahe einem Extrem; in der Zusatzrecherche vorhanden, aber nicht transcriptbestätigt. Status im Wissensgraph: `definition_pending`.

## 4. Trendlinien, Kanäle und dynamische Referenzen

- Aufwärtstrendlinie verbindet ansteigende Tiefs; Abwärtstrendlinie fallende Hochs. Sie ist eine geometrische Referenz, keine unsichtbare Order. `[P02][P06][Z01]`
- Mehrere bestätigte Berührungen erhöhen die Sichtbarkeit; extremes Nachjustieren an jeden Docht zerstört Vergleichbarkeit. `[P06]`
- **Trendkanal:** parallele Gegenlinie bildet eine Bandbreite um den Trend. Außenkante = Extremreferenz, Mittellinie = optionale Rotationsreferenz; keines davon garantiert eine Reaktion. `[Z01][Z02]`
- Ein Wick durch die Linie mit Rückschluss kann als Fakeout gelesen werden; ein klarer Schlusskurs plus Fortsetzung/Retest wird in `[P06]` als belastbarerer Bruch behandelt.
- Trendlinien können selbst sichtbare Liquidität sammeln, weil viele Marktteilnehmer ähnliche Berührungspunkte beobachten. Das bleibt ein Erklärungsmodell, kein beobachtbarer Teilnehmernachweis. `[P06]`

## 5. Candlesticks
### 5.1 Einzelkerzen

| Muster | Beobachtung | Kontextregel | Kein Beweis für |
|---|---|---|---|
| Hammer / Pin Bar unten | langer unterer Docht, kleiner Körper näher am Hoch | sinnvoller an Support/Demand/nach Sweep | automatische Long-Umkehr |
| Shooting Star / Pin Bar oben | langer oberer Docht, kleiner Körper näher am Tief | sinnvoller an Resistance/Supply/nach Sweep | automatische Short-Umkehr |
| Bullish/Bearish Engulfing | Körper/Range umfasst relevante Vorbar nach Gegenbewegung | Level und Struktur wichtiger als Name | Fortsetzung über mehrere Bars |
| Doji | Open und Close nah beieinander | Unentschlossenheit/Balance, besonders nach Expansion | Richtung |
| Momentum Candle | großer Körper, kleiner Gegendocht, Schluss nahe Extrem | Breakout/Displacement-Kontext | dass der Break hält |
| Inside Bar | gesamte Range innerhalb der Vorbar | Kompression; Richtung erst mit Ausbruch | welche Seite bricht |

Quellen: `[P03][P06][P08][Z01][Z02]`.

### 5.2 Kerzenlogik
- Kerzennamen sind eine Kurzschrift für Open–High–Low–Close-Beziehungen. Der Ort im Chart und die vorangehende Bewegung tragen mehr Kontext als der Name allein. `[P03][Z01][Z02]`
- Eine Kerze ist erst nach Close bestätigt. Intrabar-Muster können bis zum Schluss verschwinden.
- Docht und Schlusskurs getrennt speichern: `wick_breach=true` kann mit `close_acceptance=false` koexistieren.

## 6. Chart Patterns

| Musterfamilie | Struktur | Messobjekte | Scheitern/Alternative |
|---|---|---|---|
| Double Top/Bottom | zwei Tests einer Extremzone mit Zwischenpivot | Extremzone, Neckline, Abstand, zweiter Schluss | zweiter Test kann Liquidität nur sweepen oder sauber ausbrechen |
| Head & Shoulders / invers | drei Spitzen/Täler, mittlere Ausprägung extremer | Schultern, Kopf, Neckline | schiefe/uneinheitliche Geometrie, kein Neckline-Bruch |
| Triangle | konvergierende Grenzen | Hochfolge, Tieffolge, Apex, Ausbruchsseite | Ausbruch vor/nahe Apex kann unterschiedlich interpretiert werden |
| Flag/Pennant | starke Bewegung, kompakte Gegen-/Seitwärtskonsolidierung | Pole, Korrekturkanal, Break | tiefe Korrektur kann Trendstruktur zerstören |
| Rectangle/Range | horizontale Ober-/Untergrenze | Reaktionen, Fehlausbrüche, Mitte | Grenzen erweitern sich; altes Rechteck ist nicht mehr aktuell |
| Wedge | beide Grenzen steigen oder fallen und konvergieren | Steigungen, Kontaktpunkte, Break | Keilrichtung allein bestimmt Ausbruchsrichtung nicht sicher |
| Cup/rounded base | längere abgerundete Bodenbildung, optional Handle | Rand, Tiefe, Handle | subjektive Form; auf kleinen Samples leicht hineinzulesen |

- Pattern-Ziele aus gemessener Höhe sind Projektionen, keine Garantie. `[P07]`
- Muster dürfen erst nach objektiv definierten Pivots und Grenzen klassifiziert werden; andernfalls droht rückblickendes Hineinzeichnen. `[P07][Z01]`

## 7. Breakouts, Retests und False Breakouts

- **Breakout:** Preis überschreitet eine definierte Grenze. Pflichtfelder: Grenze, Richtung, Wick/Close, Body-Größe, relatives Volumen falls vorhanden, Folgebar, Retest. `[P06][P07][P08][Z02]`
- **Akzeptanz:** mehrere Abschlüsse/Rotation außerhalb oder erfolgreicher Retest; **Rejection:** Rückkehr in die alte Range. Das sind Beobachtungsbeschreibungen, keine universellen Barzahlen.
- `[P08]` bevorzugt eine klare Momentumkerze und unterscheidet aggressive Teilnahme am Close von konservativerem Retest. Die vorliegende Notiz übernimmt daraus nur die Analysemerkmale, nicht die Entry-Regel.
- **False Breakout/Fakeout:** Extrem/Level wird überschritten, Preis kann sich außerhalb aber nicht halten und schließt bzw. handelt wieder innerhalb. `[P04][P06][P08][P10][Z02]`
- Gegenbeispiel: Ein erster Rückschluss macht den Break nicht endgültig falsch; ein zweiter Impuls kann die Grenze erneut und nachhaltig brechen.

## 8. Liquidität
### 8.1 Was im Chart beobachtbar ist

- Sichtbare Referenzen: gleiche Hochs/Tiefs, markante Swingpunkte, Range-Grenzen, vorherige Tages-/Wochenhochs und -tiefs sowie offensichtliche Trendlinien. `[P05][P06][P10][P12]`
- **Buy-side liquidity (BSL):** im SMC-Modell erwartete Stops/Buy-Orders oberhalb sichtbarer Hochs. **Sell-side liquidity (SSL):** erwartete Stops/Sell-Orders unterhalb sichtbarer Tiefs. `[P10]`
- Das Chart zeigt das Level und die Reaktion, nicht die Identität oder exakte Ordermenge hinter dem Level. Deshalb `liquidity_hypothesis`, nicht `institutional_order_confirmed`.

### 8.2 Equal Highs/Lows und Pools
- Equal Highs/Lows brauchen eine Toleranz relativ zu Tickgröße oder Volatilität; mathematische Gleichheit ist zu streng.
- Ein Cluster aus mehreren nahen Extrema ist sichtbarer als ein isolierter Pivot, doch Sichtbarkeit garantiert nicht, dass Preis dorthin läuft.
- Interne Liquidität (IRL) liegt innerhalb einer Range/Bewegung; externe Liquidität (ERL) außerhalb an den Grenzen. `[P10]`

### 8.3 Sweep, Run und Grab
- **Sweep:** Level wird überschritten und zügig zurückgenommen; häufig als Stop-Auslösung plus Ablehnung interpretiert. `[P10][P11]`
- **Run:** Level wird genommen und Preis setzt in gleicher Richtung fort/akzeptiert außerhalb. `[P10]`
- Klassifikation benötigt mindestens: `level`, `penetration`, `time_outside`, `close_location`, `reentry`, `follow_through`, `opposite_structure_break`.
- Ein Sweep allein ist keine Umkehrbestätigung. In `[P10]` wird erst die nachfolgende Strukturänderung als zusätzliche Information genutzt.

### 8.4 Inducement
- Inducement ist im Modell `[P12]` ein kleinerer, sichtbarer Strukturpunkt vor dem relevanteren Block, dessen Liquidität zuerst genommen werden kann.
- Weil Inducement stark interpretationsabhängig ist, muss der Analyzer den referenzierten Pivot und die zeitliche Reihenfolge speichern; nachträgliches Umetikettieren ohne vorherige Definition ist unzulässig.

## 9. Imbalances: FVG und IFVG
### 9.1 Fair Value Gap

- Drei-Kerzen-Struktur: Bei bullischem FVG liegt zwischen Hoch der ersten und Tief der dritten Kerze ein nicht überlappter Bereich; bearish invers. `[P05][P09][P10][P13]`
- Repräsentiert schnelle einseitige Preislieferung/Imbalance. Es beweist keine „offene institutionelle Order“.
- Qualitätsmerkmale aus `[P13]`: Strukturbezug/BOS, Displacement, passende Lage in Premium/Discount, Liquiditätskontext, saubere Ausprägung und nicht beliebig häufige Mitigation.
- Widerspruch: `[P05]` behandelt kleine Teilfüllung anders als `[P13]`, das eine Mitigation strenger wertet. Deshalb `mitigation_rule_source` speichern.
- Invalidierung: je nach Modell vollständige Durchquerung, Schlusskurs jenseits der Gegenkante oder Umwandlung in IFVG. Keine universelle Regel aus den Videos.

### 9.2 Inverse FVG
- **IFVG:** ein FVG wird in Gegenrichtung durchhandelt und anschließend als umgekehrte Reaktionszone betrachtet. Die Primärplaylist erwähnt verwandtes Verhalten, definiert IFVG aber nicht vollständig; `[Z09]` ist hierfür nur Kapitel-/Beschreibungsevidenz.
- Pflichtfelder: ursprüngliche Richtung, Originalgrenzen, Inversionsbar, Wick/Close-Regel, Retest, neues Strukturregime.
- Nicht jedes gefüllte FVG ist automatisch ein IFVG; ohne definierte Inversion und Reaktion bleibt es ein mitigiertes/invalidiertes FVG.

## 10. Premium, Discount, Equilibrium und Dealing Range

- Eine definierte Swing-Range wird in obere Hälfte (**Premium**), Mitte (**Equilibrium**) und untere Hälfte (**Discount**) geteilt. `[P05][P13]`
- Das ist relative Lage innerhalb einer gewählten Range. Ändert sich die Range, ändern sich Premium/Discount.
- Das Modell liefert Kontext für Zonen/FVGs, aber keine Richtung ohne Struktur- und Liquiditätsannahme.
- Analyzer-Felder: `range_high`, `range_low`, `range_source`, `equilibrium`, `relative_position`, `range_confirmed_at`.

## 11. Volumen, Auktion und Orderflow
### 11.1 Zeitbasiertes Volumen

- Balkenvolumen misst Aktivität pro Zeitbar; hohes Volumen bedeutet hohe Teilnahme, nicht automatisch Käufe oder Verkäufe, weil jeder Trade Käufer und Verkäufer hat.
- Volumen-Expansion beim Ausbruch und Volumen-Kontraktion im Pullback wird von manchen Tradern als Trendqualitätsmerkmal genutzt; Rayner Teo weist ausdrücklich darauf hin, dass andere Trader Volumen nicht verwenden. `[Z02]`
- **Relative Volume (RVOL):** aktuelles Volumen im Vergleich zu einer historischen Referenz desselben Intervalls. Vergleichsfenster und Session-Saisonalität müssen gespeichert werden.

### 11.2 VWAP und Anchored VWAP
- **VWAP:** volumen-gewichteter Durchschnittspreis der betrachteten Session; beschreibt, wo der durchschnittliche gehandelte Preis unter Volumengewichtung liegt. `[Z03]`
- **Anchored VWAP:** dieselbe Idee ab einem bewusst gewählten Ereignis/Anker statt automatischem Sessionstart. Der Anker muss begründet und gespeichert werden. `[Z06]`
- Preis ober-/unterhalb VWAP beschreibt Lage relativ zum Durchschnitt, nicht automatisch Käufer-/Verkäuferkontrolle oder einen Entry.
- VWAP ist datenfeed- und sessionabhängig; Forex-Tickvolumen, Krypto-Börsenvolumen und zentralisiertes Futures-Volumen sind nicht identisch.

### 11.3 Volume Profile
- **POC:** Preislevel mit dem höchsten gemessenen Volumen im Profil. **VAH/VAL:** obere/untere Grenze der definierten Value Area. **HVN:** Volumencluster/hohe Akzeptanz. **LVN:** dünner Bereich/geringe Akzeptanz. `[Z05][Z13]`
- Profile können Session, sichtbaren Bereich, fixen Swing oder Kompositzeitraum abdecken. Ergebnisse sind ohne Profilgrenzen nicht vergleichbar.
- Creator interpretieren POC/HVN oft als Akzeptanz bzw. Magnet und LVN als schnelle Durchlauf-/Ablehnungszone. Das ist ein Auktionsmodell, keine garantierte Reaktion. `[Z05][Z13]`

### 11.4 Market Profile/TPO
- TPO zählt Zeit-/Opportunity-Einheiten je Preis; **Initial Balance** ist die frühe Eröffnungsrange nach der verwendeten Sessiondefinition. `[Z14]`
- POC und Value Area existieren auch hier, beruhen aber auf TPO/Time-at-Price statt zwingend echtem Volumen.
- Profile Shape, Value-Migration und Akzeptanz/Rejection beschreiben die Auktion. Sie dürfen nicht mit Volume Profile gleichgesetzt werden.

### 11.5 Delta, CVD und Footprint
- **Delta:** aggressives Ask-Volumen minus aggressives Bid-Volumen im betrachteten Intervall. **CVD:** kumulierte Summe dieses Deltas. `[Z12]`
- CVD-Divergenz vergleicht nahe, sachlich zusammengehörige Preisextrema mit CVD-Extrema. `[Z12]` warnt vor weit auseinanderliegenden, beliebig verbundenen Punkten, weil frühere Absorption die Basis verschiebt.
- **Absorption:** viel aggressive Aktivität erzeugt wenig Preisfortschritt; sie ist kontext- und levelabhängig und kein alleiniger Richtungsbeweis. `[Z12]`
- Footprint-Imbalance vergleicht ausgeführtes Bid-/Ask-Volumen auf Preisleveln. Ohne echte Aggressor-Klassifikation oder zentralen Feed kann das Signal unvollständig sein.

### 11.6 Open Interest, Funding und Liquidationen
- **Open Interest (OI):** Zahl/Größe offener Derivatekontrakte; steigend bedeutet Positionsaufbau, aber nicht von allein bullish oder bearish. `[Z20]`
- **Funding Rate:** periodischer Ausgleich bei Perpetual Futures; Vorzeichen und Höhe zeigen relative Positionierungs-/Preisverzerrung zwischen Long und Short, nicht sicheren Kursverlauf. `[Z15]`
- **Liquidationen:** zwangsweise Schließungen gehebelter Positionen; Heatmaps zeigen modellierte Cluster, keine garantierten Ziele. `[Z20]`
- Gemeinsame Leselogik: Preisänderung, OI-Änderung, Funding, Spot-/Perp-Volumen und Liquidationen getrennt speichern; keine Richtung aus nur einer Serie ableiten.

## 12. Indikatoren — vollständige Funktionslandkarte

> [!rule] Grundregel
> Indikatoren transformieren historische Preis-, Volumen- oder Derivatdaten. Zwei Indikatoren derselben Familie können dieselbe Information unterschiedlich glätten und sind dann keine unabhängige Bestätigung. `[Z01][Z02][Z03]`

### 12.1 Trend und Regime

| Indikator | Eingabe/Ausgabe | Wofür die Videos ihn einordnen | Typische Fehlinterpretation |
|---|---|---|---|
| SMA | geglätteter Durchschnitt über Lookback | Trend-/dynamische Value-Referenz | Crossover als sichere Prognose |
| EMA | stärker jüngste Preise gewichteter Durchschnitt | schnellere Trend-/Pullback-Referenz | mehrere EMAs als unabhängige Signale zählen |
| MACD | Differenz geglätteter Reihen plus Signallinie/Histogramm | Trendmomentum und Momentumwechsel `[Z03]` | Cross ohne Regimekontext |
| ADX | dimensionslose Trendstärke | Stärke, nicht Richtung `[Z03]` | hoher ADX = bullish |
| DMI (+DI/−DI) | gerichtete Bewegungsanteile | Richtungskomponente neben ADX `[Z03]` | DI-Cross allein als Entry |
| Supertrend | volatilitätsbasierte Trendlinie/Regimefarbe | Trendfolge in verschiedenen Marktumfeldern `[Z03]` | häufiges Flippen in Seitwärtsmärkten ignorieren |
| Parabolic SAR | Punkte wechseln relativ zum Preis | Momentum-/Trendfolge und mögliche Wechselpunkte `[Z16]` | in flachen Ranges jeden Flip handeln |
| Ichimoku Cloud | mehrere zeitversetzte Mittel-/Range-Linien | Gesamttrend, Balancezone, dynamische Bereiche `[Z16]` | Cloud allein als Marktstruktur gleichsetzen |

### 12.2 Momentum-Oszillatoren

| Indikator | Misst | Lesbare Information | Grenze |
|---|---|---|---|
| RSI | relative Stärke jüngster Auf-/Abbewegungen | Momentum, Extremzonen, Divergenz `[Z03]` | „overbought“ kann in starkem Trend lange bestehen |
| Stochastic | Close-Lage innerhalb jüngster High-Low-Range | kurzfristige Range-Position/Momentum | Extremwert ist keine Umkehrgarantie |
| Stochastic RSI | Stochastic-Transformation des RSI | schnellere Lage des RSI in eigener Range | doppelte Ableitung erhöht Rauschen |
| Williams %R | invertierte Close-Lage in jüngster Range | Momentumextreme | ähnlich Stochastic; keine unabhängige Bestätigung |
| CCI | Abweichung eines typischen Preises von seinem Mittel | zyklische Überdehnung/Momentum | feste Schwellen sind markt-/lookbackabhängig |
| ROC/Momentum | Preisänderung gegenüber Lookback | Geschwindigkeit/Richtung der Veränderung | stark von Lookback und Ausreißern abhängig |

### 12.3 Volatilität und Kanäle

| Indikator | Misst | Lesbare Information | Grenze |
|---|---|---|---|
| ATR | historische True-Range-Volatilität | Bewegungsgröße/Volatilität; `[Z02]` nutzt ATR als Distanzpuffer | keine Richtung; ATR steigt auch in Abverkäufen |
| Bollinger Bands | gleitender Mittelwert plus streuungsbasierte Bänder | Volatilitätsausweitung/-kompression, relative Lage `[Z03]` | Bandberührung ist nicht automatisch Reversal |
| Keltner Channel | Mittelwert plus volatilitätsbasierte Bänder | Trend und Volatilitätsänderung `[Z17]` | Whipsaws in flachen Märkten |
| Donchian Channel | höchstes Hoch/tiefstes Tief des Lookbacks | Range-Grenzen und neue Extrempreise | verspätet und fakeout-anfällig in Ranges |
| Historical Volatility | Streuung vergangener Renditen | Regimevergleich | vergangene Streuung sagt Sprungrisiko nicht vollständig voraus |
| VIX/implizite Volatilität | optionsbasierte erwartete Schwankung eines Markts | Risiko-/Volatilitätsregime | kein direkter Richtungsindikator für jeden Einzelwert |

### 12.4 Volumen und Money Flow

| Indikator | Misst | Lesbare Information | Grenze |
|---|---|---|---|
| Raw Volume/RVOL | Aktivität absolut/relativ | Teilnahme, Breakout-/Eventintensität | Volumen ist nicht Richtung |
| VWAP/AVWAP | volumen-gewichteter Durchschnitt | Lage relativ zu Session/Ereigniswert `[Z03][Z06]` | Anker und Feed verändern Ergebnis |
| OBV | kumuliert Volumen nach Up-/Down-Close | Volumentrend und Divergenz `[Z18]` | gesamtes Barvolumen wird einer Richtung zugeordnet |
| Chaikin Money Flow | Close-Lage in Bar, gewichtet mit Volumen | Kauf-/Verkaufsdruck über Fenster `[Z19]` | Close-Lage ist Proxy, kein echter Orderflow |
| Money Flow Index | Preis und Volumen als Oszillator | volumen-gewichtetes Momentum/Extrem | Extremzonen können in Trends bestehen |
| Volume Profile | Volumen je Preis | POC, Value, HVN/LVN `[Z05][Z13]` | Zeitraumsauswahl bestimmt das Profil |

### 12.5 Level-, Verhältnis- und Zeitwerkzeuge

| Werkzeug | Basis | Richtige Rolle | Grenze |
|---|---|---|---|
| Pivot Points | vorherige Periodenpreise | vorab berechnete Referenzlevels `[Z03]` | viele Varianten; kein Level ist garantiert |
| Fibonacci Retracement/Extension | zwei oder drei gewählte Anker | relative Rücklauf-/Projektionsniveaus `[P07][Z02]` | Ankerwahl subjektiv; Verhältnis ist kein Beweis |
| Previous Day/Week High/Low | historische Sessionextrema | Struktur-/Liquiditätsreferenz `[P10]` | verliert Relevanz je nach Regime/Distanz |
| Session Open/Range | definierter Zeitstart | Intraday-Lage und Expansion | Zeitzone, DST und Produkt-Session beachten |
| Opening Range/Initial Balance | frühe Sessionrange | frühes Balance-/Expansionsmaß `[Z14]` | Dauer ist markt-/frameworkabhängig |

### 12.6 Redundanzprüfung

- RSI, Stochastic, StochRSI und Williams %R sind alle Momentum-/Range-Lage-Werkzeuge; vier gleiche Richtungen sind nicht vier unabhängige Belege.
- SMA, EMA, MACD und Supertrend sind stark preis- und glättungsbasiert; sie reagieren verzögert auf dieselbe Historie.
- ATR, Bollinger und Keltner beschreiben verschiedene Formen von Volatilität/Abstand, nicht Orderflow.
- VWAP, Volume Profile, OBV/CMF und CVD verwenden Volumen unterschiedlich: Durchschnittspreis, Volumen je Preis, Bar-Proxy und Aggressor-Flow dürfen nicht vermischt werden.

### 12.7 Erweiterte Indikator- und Darstellungsinventur

| Familie | Weitere Werkzeuge | Was sie tatsächlich transformieren | Hauptgrenze |
|---|---|---|---|
| Moving Averages | WMA, VWMA, HMA, DEMA, TEMA, KAMA | Preis/Volumen mit anderer Gewichtung und Verzögerung | neue Glättung ist keine neue Informationsquelle |
| Trend/Momentum | PPO, TRIX, Aroon, Vortex, Mass Index, Elder Impulse | geglättete Preisänderung, Zeit seit Extrem oder Range-Ausweitung | Parameter- und Regimeabhängigkeit; Whipsaw |
| Oszillatoren | Ultimate Oscillator, KDJ, Fisher Transform, Coppock, Chande Momentum | normierte Lage/Änderung über einen oder mehrere Lookbacks | Extremwert und Divergenz sind keine zeitgenauen Trigger |
| Volatilität | Standardabweichung, Chaikin Volatility, Choppiness Index, Ulcer Index | Renditestreuung, Rangeänderung, Trendigkeit oder Drawdownschmerz | unterschiedliche Definitionen nicht austauschbar |
| Volumenfluss | Accumulation/Distribution, Chaikin Oscillator, Force Index, Ease of Movement, Klinger, NVI/PVI | Barpreisposition/-änderung kombiniert mit Volumenproxy | keine direkte Identifikation institutioneller Käufer/Verkäufer |
| Marktbreite | Advance/Decline, Up/Down Volume, New High-Low, McClellan, Prozent über MA | Beteiligung vieler Komponenten eines Universums | Universums-, Gewichtungs- und Survivorship-Bias |
| Relative Stärke | Ratio-Chart, Relative Rotation, Beta, Rolling Correlation | Verhältnis oder gemeinsame Bewegung zweier Reihen | Fensterwechsel und Korrelation ≠ Kausalität |
| Derivate | Put/Call, IV Rank/Percentile, Skew, Term Structure, Max-Pain-Darstellung | Optionspreise, Volumen/OI und Laufzeitstruktur | Datenlatenz, Hedgingrichtung und „Max Pain“ nicht als Magnet beweisen |
| Sentiment/Positionierung | COT, Long/Short Ratio, Funding, Short Interest | meldepflichtige/venue-spezifische Bestände oder Finanzierung | Veröffentlichung verzögert; Gegenpartei und Motivation unklar |
| Alternative Bars | Heikin-Ashi, Renko, Kagi, Point-and-Figure, Range/Tick/Volume Bars | gefilterte oder ereignisbasierte Preisaggregation | synthetische OHLC-Werte können nicht direkt handelbar sein |
| Geometrie/Zeit | Gann, Andrews Pitchfork, Regression Channel, Standard Deviation Channel | gewählte Anker und mathematische Linien | hohe Freiheitsgrade erzeugen rückblickende Passform |
| Pivotvarianten | Classic, Woodie, Camarilla, Fibonacci, DeMark | vorige Perioden-OHLC nach unterschiedlicher Formel | konkurrierende Levels; keine Variante universell überlegen |

- Eine „vollständige Indikatorliste“ ist prinzipiell offen, weil beliebige Transformationen programmiert werden können. Das Gehirn speichert daher für jeden Indikator die universellen Felder `input_series`, `venue`, `lookback`, `formula_version`, `output_unit`, `lag`, `family`, `failure_modes` und `source`, statt Namen als eigenständige Wahrheiten zu behandeln.
- Vor Verwendung prüfen: repaintet das Skript, nutzt es höhere Timeframes mit noch offenen Bars, enthält es Zukunftsdaten, wechselt der Anbieter die Formel, sind Splits/Rolls angepasst, und ist der angezeigte Wert historisch reproduzierbar?

## 13. Multi-Timeframe-Analyse

1. **HTF-Regime:** Trend, Range oder Übergang bestimmen.
2. **HTF-Referenzen:** markante Swings, S/R, Supply/Demand, externe Liquidität, vorherige Sessionextrema markieren.
3. **Mittlerer Timeframe:** aktuelles Leg, interne Struktur, Premium/Discount, FVG/Block-Kontext beschreiben.
4. **LTF-Beobachtung:** Sweep, Rejection, Displacement, BOS/CHoCH/MSS oder Akzeptanz erfassen.
5. **Konflikt speichern:** HTF bullish + LTF bearish ist kein Fehler; der LTF kann einen Pullback beschreiben. `[P04][P10][P12][Z02]`

Der Analyzer gibt kein binäres „bullish“, wenn die Timeframes widersprechen, sondern z. B. `HTF_uptrend / MTF_discount_pullback / LTF_bearish_internal_structure`.

## 14. Sessions und zeitliche Liquidität

- Märkte haben wiederkehrende Aktivitätsfenster; Liquidität und Volatilität unterscheiden sich nach Produkt, Zeitzone und Session. `[P01][P10]`
- Speichere Asia/London/New York bzw. Produkt-spezifische Cash-/Futures-Session nur mit expliziter Zeitzone und DST-Regel.
- Session High/Low, Open, VWAP, Initial Balance, Volumen und Range sind eigenständige historische Referenzen.
- Session-Übergänge können Expansion bringen, aber die Playlist liefert keine universelle „beste Uhrzeit“. Deshalb keine feste Handelszeit als Regel übernehmen.

## 15. Wirtschaftskalender und Newswirkung

### 15.1 Kalendereintrag

- **Actual:** veröffentlichter Wert. **Forecast/Consensus:** erwarteter Wert. **Previous:** Vorperiode, eventuell revidiert. **Impact:** historische/erwartete Bewegungsrelevanz des Events. `[Z10][Z11]`
- Der Markt reagiert häufig auf die **Überraschung Actual minus Forecast** und auf Revisionen, nicht isoliert auf „hoch“ oder „niedrig“.
- Wirkung ist relativ zu bereits eingepreisten Erwartungen, Positionierung und gleichzeitig veröffentlichten Komponenten. Darum keine Regel „CPI über Forecast = Index fällt immer“.

### 15.2 Eventfamilien

| Event | Informationskern | Typische betroffene Achsen | Analysefelder |
|---|---|---|---|
| CPI/PCE/PPI | Inflation/Preisdruck | Zins­erwartungen, Währung, Anleihen, Indizes, Gold | headline/core, MoM/YoY, surprise, revision |
| NFP/Arbeitsmarkt | Beschäftigung, Löhne, Arbeitslosigkeit | Wachstum und Zinspfad | payroll surprise, unemployment, wages, revisions |
| FOMC/Zinsentscheid | Leitzins, Projektionen, Kommunikation | gesamte Zinskurve und Risikoassets | decision, statement, projections, press conference |
| GDP/PMI/Retail Sales | Wachstum/Aktivität/Nachfrage | zyklische Assets, Währungen, Zinsen | actual, forecast, components, revision |
| Earnings/Guidance | Unternehmensdaten und Ausblick | Einzelwert, Sektor, Index | EPS/revenue surprise, guidance, gap, volume |

### 15.3 Chartwirkung

- Vor wichtigen Releases kann der Markt konsolidieren oder Positionen abbauen; nach Veröffentlichung können Spread, Slippage, Range und Volumen sprunghaft steigen. `[P01][Z10][Z11]`
- Die erste News-Kerze kann beide Seiten einer Range durchlaufen. Ihr High/Low wird danach zur historischen Referenz, ist aber kein sicherer Support/Resistance.
- FOMC umfasst mindestens Entscheidung/Statement und oft spätere Pressekonferenz; unterschiedliche Phasen können gegensätzliche Moves erzeugen.
- Pflichtfelder für historische Auswertung: Eventzeit in Exchange-Zeitzone, Werte/Revisionen, 5/15/30/60-Minuten-Returns, Max Adverse/Favorable Excursion, Volumen, Spread falls verfügbar, Regime vor dem Event.

## 16. Historische Daten und Chartkontext

- **Historische Referenzen:** Previous Day/Week/Month High/Low, Open/Close, Sessionrange, Gap, VWAP/POC/Value Area, Swingstruktur, Eventkerzen. `[P10][Z05][Z13][Z14]`
- **Normalisierung:** Entfernungen nicht nur in Punkten, sondern relativ zu Tickgröße, ATR oder typischer Sessionrange speichern; sonst sind Märkte und Regime nicht vergleichbar.
- **Regime-Segmentierung:** Trend, Range, hohe/niedrige Volatilität, News-/Non-News-Tag und Session getrennt auswerten.
- **Keine Zukunftsdaten:** Swingbestätigung, Tageshoch und finales Volumen dürfen erst verwendet werden, wenn sie zum Analysezeitpunkt bekannt waren.
- **Walk-forward statt Rückschau:** Regeln auf früheren Daten definieren, späteren Daten prüfen; Parameteränderungen versionieren. `[P01][P02]`
- Ein historisches Beispiel ist Illustration. Erst eine Stichprobe mit Verlustfällen zeigt, ob ein Analysemerkmal stabil ist; Creator-Profitclaims ersetzen diese Prüfung nicht.

## 17. Konfluenz ohne Doppelzählung

- Konfluenz bedeutet mehrere **verschiedene Informationsfamilien** stimmen in einer Hypothese überein: Struktur, Ort/Zone, Liquiditätsereignis, Volatilität, Teilnahme/Volumen, Zeit/News.
- Drei Momentumindikatoren sind eine Familie. Ein FVG und die große Displacement-Kerze, die es erzeugt, sind ebenfalls nicht vollständig unabhängig.
- Für jeden Befund speichern: `family`, `direction`, `strength`, `freshness`, `timeframe`, `source`, `dependent_on`.
- Gegenevidenz explizit führen: z. B. HTF-Resistance gegen bullischen LTF-BOS; negatives CVD gegen steigenden Preis; News in fünf Minuten gegen ruhiges technisches Bild.

## 18. Widersprüche und Definitionen, die nicht vereinheitlicht werden dürfen

| Thema | Variante A | Variante B | Speicherregel |
|---|---|---|---|
| Strukturbruch | Wick genügt | Schlusskurs/Displacement nötig | `break_method` |
| S/R | häufige Tests bestätigen Sichtbarkeit | viele Tests verbrauchen Zone | Modelltyp getrennt speichern |
| Order Block | letzte Gegenkerze | Basis/Teilbereich/Body | `zone_method` + Quelle |
| FVG-Mitigation | erster Touch relevant | tiefere/volle Füllung nötig | `mitigation_rule_source` |
| CHoCH/MSS | Synonyme | MSS = Sweep + Displacement + Gegenbruch | `definition_variant` |
| Volumen | wichtiger Breakoutfilter | optional; manche Price-Action-Trader nutzen es nicht | kein globales Pflichtsignal `[Z02]` |
| Overbought/Oversold | mögliche Umkehrzone | Trendstärke kann Extrem lange halten | Regime zuerst |
| POC/HVN | „Magnet“/Akzeptanz | kann bei Regimewechsel ohne Reaktion durchhandelt werden | nur Profilbeobachtung |

## 19. Maschinenlesbare Wissenskarten für Obsidian

```yaml
concept: liquidity_sweep
framework: SMC
source_definition: P10
market: ES
timeframe: 15m
session: New_York
observed_at: 2026-09-30T15:30:00+02:00
reference_level:
  type: previous_day_high
  price: 0.0
observation:
  wick_breach: true
  close_back_inside: true
  follow_through_bars: 0
confirmation:
  displacement: unknown
  choch: false
status: observation_only
invalidated_if: acceptance_above_reference
```

### 19.1 Pflichtlogik

- `observation` = direkt aus Daten messbar.
- `interpretation` = Framework-Deutung, immer mit `source_definition`.
- `hypothesis` = erwartbares Szenario, nie als Fakt speichern.
- `confirmation` = vorher definierte Zusatzbedingung.
- `invalidation` = Bedingung, unter der die Interpretation nicht mehr gilt.
- `outcome` = spätere Beobachtung; darf ursprüngliche Felder nicht rückwirkend verändern.

### 19.2 Analyseausgabe

```yaml
regime: range
htf_structure: bullish
location: htf_resistance
liquidity:
  nearest_bsl: previous_week_high
  nearest_ssl: equal_lows
imbalances:
  bullish_fvg: present_unmitigated
volume_context: below_session_average
news:
  high_impact_within_minutes: 18
conflicts:
  - bullish_internal_bos_vs_htf_resistance
unknowns:
  - orderflow_feed_unavailable
conclusion: context_only_no_strategy_signal
```

## 20. Analyse-Checkliste

1. Sind Symbol, Börse, Datenfeed, Zeitzone, Session und Timeframe eindeutig?
2. Ist der aktuelle Balken geschlossen oder live?
3. Welches Regime zeigen HTF und Ausführungs-Timeframe getrennt?
4. Welche Swings und Strukturpunkte waren zum Analysezeitpunkt bereits bestätigt?
5. Wo liegen S/R, Supply/Demand, Profile-Value und sichtbare Liquidität?
6. Befindet sich Preis in Expansion, Pullback, Balance oder Übergang?
7. Gab es Break, Akzeptanz, Rejection, Sweep oder Run – nach welcher Definition?
8. Liegen FVG/IFVG/Block vor, und welche Qualitäts-/Invalidierungsregel wird verwendet?
9. Was sagen Volatilität, Volumen und ggf. Orderflow; sind Daten dafür valide?
10. Welche Indikatoren messen dieselbe Grundinformation und dürfen nicht doppelt zählen?
11. Welche Session- und Newsereignisse stehen unmittelbar bevor oder liegen gerade zurück?
12. Welche Gegenevidenz und welche unbekannten Daten fehlen?

## 21. Quellenkorpus

### 21.1 Vollständig ausgewertete Primärvideos

| ID | Video | Creator | URL | Evidenz |
|---|---|---|---|---|
| P01 | In nur 10 Minuten Daytrading verstehen! | Finanzfluss | https://www.youtube.com/watch?v=W9rc0RQvf0s | A |
| P02 | Als Anfänger SCHNELL Traden lernen! | Henry F. | https://www.youtube.com/watch?v=B6xG-m2fn78 | A |
| P03 | The ONLY Candlestick Pattern Guide You'll EVER NEED | TradingLab | https://www.youtube.com/watch?v=tW13N4Hll88 | A |
| P04 | Secret Formula For Drawing Support & Resistances | TradingLab | https://www.youtube.com/watch?v=9NbmBDUysOA | A |
| P05 | FVG Trading Strategy Explained | Trader Tips | https://www.youtube.com/watch?v=yJDaddL6SB4 | A |
| P06 | The ONLY Trendline Trading Video You NEED in 2026! | TradingLab | https://www.youtube.com/watch?v=8nIoOnGOZU8 | A |
| P07 | Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen | The Moving Average | https://www.youtube.com/watch?v=WbMnfiknBoc | A |
| P08 | How to Avoid False Breakouts | TradingLab | https://www.youtube.com/watch?v=ZudTPpJCbbA | A |
| P09 | The ULTIMATE Supply & Demand Guide | TradingLab | https://www.youtube.com/watch?v=fPSQ_NnmqWI | A |
| P10 | Liquidity Sweep Trading Strategy Explained | Trader Tips | https://www.youtube.com/watch?v=Skn0eSmryO8 | A |
| P11 | So erkennst du einen Orderblock | Noc Trading | https://www.youtube.com/watch?v=AwxIbna0By4 | A; Spur endet 04:03/06:47 |
| P12 | I Found a Secret To Orderblocks | TradingLab | https://www.youtube.com/watch?v=qmsGqitE2LE | A |
| P13 | I Found A Secret To Fair Value Gaps | TradingLab | https://www.youtube.com/watch?v=ZTMregh_428 | A |

### 21.2 Zusatzvideos und sichtbare Transkript-/Kapitelevidenz

| ID | Video | Creator | URL | Verwendbarer Stand |
|---|---|---|---|---|
| Z01 | The Only Technical Analysis Video You Will Ever Need | The Trading Channel | https://www.youtube.com/watch?v=eynxyoKgpng | B; substantieller Transkriptmirror |
| Z02 | Technical Analysis Was Hard Till I Discovered This SECRET | Rayner Teo | https://www.youtube.com/watch?v=bQZ_hhg6gmE | A; veröffentlichtes Volltranskript |
| Z03 | Complete Trading Indicators: RSI, MACD, VWAP & More | PhyZan | https://www.youtube.com/watch?v=mAkqhKtDXf4 | B; ausführliche Kapitelbeschreibung |
| Z05 | Volume Profile Trading Strategy: Value Area, POC | Chart Padhna Sikho | https://www.youtube.com/watch?v=qQdyTEo0Ft8 | B; Definitionen in Beschreibung |
| Z06 | Day Trading With Anchored VWAP & Volume Profile | Trader Dale | https://www.youtube.com/watch?v=nbdLCKBGv7k | B; Themen-/Kapitelevidenz |
| Z09 | Inversion Fair Value Gaps (IFVG) — ICT Concepts | TTrades | https://www.youtube.com/watch?v=uDJI2AbyyCs | B; Themen-/Kapitelevidenz |
| Z10 | How to trade High-Impact Fundamentals (NFP, CPI, FOMC) | Live Trade Videos | https://www.youtube.com/watch?v=kT4eU_kOCGs | B; Beschreibung |
| Z11 | ICT 2026 Smart Money Concepts Lecture — Jan 29 | Inner Circle Trader | https://www.youtube.com/watch?v=8wHewi6N6dg | B; Transkriptauszug zu Kalender/News |
| Z12 | Orderflow: How to read Cumulative Delta the RIGHT way | Axia Futures | https://www.youtube.com/watch?v=TIeSFhLrK2U | A/B; umfangreicher Transkripttext |
| Z13 | How to Use Volume Profile: LVN, HVN & POC | Keshav Jindal | https://www.youtube.com/watch?v=9Qv6rYttZsU | B; ausführliche Kapitelbeschreibung |
| Z14 | Learn Market Profile from Scratch: TPO, POC, Value Area & IB | Orderflowtalks | https://www.youtube.com/watch?v=R-ueIHMLI7w | B; ausführliche Kapitelbeschreibung |
| Z15 | Funding Rates Explained | FinTools | https://www.youtube.com/watch?v=nkazrGjuisE | B; Definitionen/Kapitel in Beschreibung |
| Z16 | Ichimoku Cloud + Parabolic SAR | Trading Master | https://www.youtube.com/watch?v=gN9E3hcc0Q0 | B; Definitionen/Grenzen in Beschreibung |
| Z17 | Keltner Channel Explained for Beginners | Soheil PKO | https://www.youtube.com/watch?v=ylmMOcYPtQw | B; ausführliche Beschreibung |
| Z18 | On Balance Volume Indicator Explained | Soheil PKO | https://www.youtube.com/watch?v=sSxBpt61Qfo | B; ausführliche Beschreibung |
| Z19 | Chaikin Money Flow Indicator Explained | David Moadel | https://www.youtube.com/watch?v=FXmokJtK2Vs | B; Transkript-/Beschreibungstext |
| Z20 | Liquidation Heatmap + Open Interest Masterclass | The Finance School | https://www.youtube.com/watch?v=cMoC4wreQHU | B; Definitionen/Themen in Beschreibung |
| Z21 | Order Types Explained: Market, Limit & Stop Orders for Beginners | Interactive Brokers | https://www.youtube.com/watch?v=Zf37t7njppg | B; offizielle Bildungsbeschreibung und sichtbare Definitionen |
| Z22 | Getting Started with Futures | CME Group | https://www.cmegroup.com/education/videos/cme-group-getting-started-with-futures-class | B; offizielles ausführliches Bildungsvideo zu Kontrakten, Margin und Settlement |
| Z23 | What is Contango and Backwardation? | CME Group | https://www.youtube.com/watch?v=B3V7Go_CNkQ | B; offizielles Bildungsvideo und Begleittext |
| Z24 | Option Greeks Explained for Beginners | projectfinance | https://www.youtube.com/watch?v=SFebmSYSZA8 | B; ausführliche Kapitel-/Beschreibungsevidenz zu Delta, Gamma, Theta und Vega |
| Z25 | Implied Volatility and the IV Crush / What is Implied Volatility? | Options Industry Council | https://www.optionseducation.org/videolibrary/implied-volatility-and-the-iv-crush | B; offizielles Ausbildungsvideo und Begleittext |
| Z26 | US Dollar Index (DXY) Explained: How It Affects Gold, Stocks & Emerging Markets | 3-Minute Explanation | https://www.youtube.com/watch?v=By3rxDk1ox4 | B; nur als bedingte Korrelationsbehauptung, nicht als Marktgesetz |
| Z27 | Carry Trade Basics | Khan Academy | https://www.khanacademy.org/economics-finance-domain/core-finance/money-and-banking/currency-tutorial/v/carry-trade-basics | B; Ausbildungsvideo zu Zinsdifferenz und Carry-Mechanik |

### 21.3 Transparente Abdeckung

- Die Primärplaylist ist vollständig erfasst; Details stehen in `video_sources.md`.
- Die breit angelegte YouTube-Suche enthält 329 deduplizierte Zusatzkandidaten zu 14 Themenclustern. Diese Kandidaten sind **nicht automatisch analysierte Quellen**.
- YouTube lieferte nach den ersten vollständigen Abrufen weitere Caption-Endpunkte wegen automatisiertem Traffic nicht aus. Deshalb kennzeichnet diese Datei Zusatzquellen als A/B/C und behauptet nicht, hunderte Volltranskripte gelesen zu haben.
- Die Indikatorlandkarte enthält die analytische Rolle der Werkzeuge. Feste Parameter, Schwellen oder daraus gebaute Entries gehören erst nach voll belegter Creator-Regel und separatem Backtest in eine Strategie-Notiz.
- Offizielle Bildungsquellen von Börsen/Branchenorganisationen wurden für Instrument- und Ausführungsmechanik ergänzt, wenn YouTube-Transkripte nicht zuverlässig ausgeliefert wurden. Sie sind als B gekennzeichnet und ersetzen keine behauptete Volltranskriptanalyse.

