---
typ: architektur
status: laufend
aktualisiert: 2026-10-21
naechster_schritt: Heatmap gegen die Tardis-Gratistage messen, bevor ein Dauersammler startet
tags: [terminal, oberflaeche, bewertung, faktoren, journal, liquiditaet, optionen]
---

# 🖥 Darkwood Terminal — Oberfläche & Bewertungsschicht

Das Terminal unter `/terminal` auf dem **Plan-Dashboard (Port 8788**, nicht 8000;
das Live-Dashboard liegt auf 8787). Diese Notiz hält fest, was die Oberfläche
zeigt, **woher jede Zahl kommt** und — wichtiger — welche Zahlen bewusst fehlen.

> [!important] Die Regel, die über allem steht
> Eine erfundene Ebene im Chart wäre der schlimmste Fehler hier. Jede Zeile
> unten nennt ihre Quelle, und wo keine existiert, steht die Absage statt
> einer Linie. Siehe [[📡 Datenquellen — was es gibt und was nicht]].

## Faktor-Aufschlüsselung — jeder Klick zeigt den Rechenweg

Das Bot-Panel trug acht Karten mit je einem Satz. Darunter lagen **199
Einzelmessungen**, von denen die API nur die Zahl 199 meldete. Ein Klick auf
eine Karte öffnet jetzt die Aufschlüsselung: 13 Faktoren, jeder mit seinen
Unterfaktoren.

Jede Zeile trägt die **vollständige Herkunft ihres Gewichts**:

```
Gewicht = Familie × Regime × Zeitebene × Unabhängigkeit × Frische
```

mit einem Satz je Teil. Beispiele aus der laufenden Messung:

| Teil | Beispiel | Woher |
|---|---|---|
| Familie | Lage 0.90, Struktur 1.00, Volatilität 0.30 | `DEFAULT_FAMILY_WEIGHTS` |
| Regime | Momentum ×1.40 im Seitwärts, ×0.35 im Trend | `REGIME_MODIFIERS` |
| Zeitebene | W1/D1 1.00, H4/H1 0.90, M15 0.40 | `TIMEFRAME_WEIGHTS` |
| Unabhängigkeit | FVG, das seine Ursprungskerze nennt → ×0.50 | `independence_weights` |
| Frische | Halbwertszeit 40 Kerzen | `FRESHNESS_HALF_LIFE_BARS` |

**Die Gewichte werden importiert, nicht abgeschrieben.** Eine Kopie der Tabellen
in der Ansicht hätte nach der ersten Änderung an der Engine einen Rechenweg
gezeigt, der das daneben stehende Rating nicht mehr erklärt.

> [!warning] Der Satz, den die Oberfläche sagen muss
> Eine Familie **summiert ihre Mitglieder nicht** — sie nimmt den Median,
> innerhalb einer Zeitebene und gewichtet über die Ebenen. Ein Gewicht sagt
> darum nicht, wie viel eine Messung *beiträgt*, sondern wie schwer sie wiegt,
> wenn ausgewählt wird, wer in der Mitte liegt. Darum steht neben keiner Zeile
> eine Beitragszahl — die gibt es nicht.

Dazu je Indikator seine **bekannten Schwächen** aus der Registry (44 Stück,
übersetzt): „Mehrere EMAs als unabhängige Signale gezählt", „Hoher ADX als
bullisch gelesen — er misst Stärke, nicht Richtung".

Nicht-direktionale Messwerte (ADX, ATR, Choppiness, relatives Volumen) stehen
getrennt unter *Kontext*: sie haben eine Grösse, aber keine Seite. „Wird nicht
gezählt" und „wurde nicht gemessen" sind verschiedene Dinge.

## Zonen — einzeln bewertet

Vier zählbare Grössen je Zone, Gewicht ist ihr **Produkt**:

```
Nähe      Abstand zur näheren KANTE, nicht zur Mitte
Frische   Alter in Kerzen, Halbwertszeit 40
Schärfe   Breite in ATR; über eine ganze ATR ist es eine Gegend
Halt      Berührungen gegen Schlüsse auf der anderen Seite
```

Ein Produkt, keine Summe: eine Zone, die der Preis zerschnitten hat, ist nicht
halb so gut, sondern erledigt. Gemessen auf BTC am 21.10.: eine scharfe, nie
gebrochene Kante bei 82'837–82'855 → 3 Sterne (0.582); ein 2.5 ATR breites
„Angebot" nach 51 Berührungen → null.

Ein **Docht** durch die Zone zählt als Berührung, erst ein **Schluss** auf der
anderen Seite als Bruch. Anders herum hätte jeder Volatilitätsschub alle Zonen
als gebrochen markiert.

> [!danger] Was die Sterne nicht sind
> Sie messen **Relevanz, nicht Wahrscheinlichkeit**. 35 Merkmale dieser Art
> erreichten gegen die nächsten 5–10 Stunden eine Korrelation von **0.004**
> ([[📊 Evidenzstand]]). Fünf Sterne heissen „sieht gerade wichtig aus".

## Grosse Trades — mit Beträgen, ohne Etikett

Nicht „institutionelle Liquidität": das Orderbuch ist **anonym**, und welche
Seite ein Fonds ist, steht in keinem öffentlichen Feld.

Die Schwelle ist **gemessen, nicht gesetzt** — das oberste Promille des Tages.
BTCUSDT am 19.10.2026 aus dem Tagesarchiv:

```
1'002'851 Trades, Median 249 USD
p99.9 = 711'227 USD  →  1'003 Trades
zusammen 1.49 Mrd USD = 14.1 % des Tagesumsatzes
grösster einzelner Abschluss: 31'145'512 USD
```

Gezeichnet rechts, Betrag je Preisstufe beschriftet (101.9 Mio bei 82'480),
Farbe aus der Aggressor-Aufteilung. Dazu offenes Interesse (7.86 Mrd USD auf
BTC) und die Positionierung der grossen Konten.

**Liquidationen fehlen und bleiben weg:** `allForceOrders` antwortet dieser
Leitung mit der Fehlerseite der Börse, der WS-Strom liegt auf `fstream`, das
für diese Leitung stumm ist — dritter unabhängiger Befund nach
[[🚨 Monitoring & Incidents]].

## Optionen — die Strikes, nicht das Vorzeichen

GEX = offene Kontrakte × Black-Scholes-Gamma × **ein Vorzeichen, das nirgends
steht**. Nachgerechnet auf BTC: brutto 571 Mio gegen netto 181 Mio USD je 1 %.
Das Vorzeichen entscheidet über zwei Drittel der Zahl → **keine GEX-Linie**.

Gezeichnet wird der **Betrag** der Gamma-Last je Strike. Gerechnet, nicht aus
offenem Interesse abgelesen, und dieser Unterschied ist der Grund für den
Aufwand: der 60'000er Put trägt 10'955 Kontrakte und hat bei Spot 84'500 ein
Gamma nahe null. Was oben steht, steht am Geld — 80'000 mit 52.9 Mio je 1 %,
90'000 mit 50.3, 82'000 mit 50.2.

**Welche Märkte Optionen haben, gemessen am 21.10.:** Deribit führt nur BTC
(886 Instrumente) und ETH (768). Winzig anderswo: BNB 0.155 %, AVAX 0.030 %,
XRP 0.024 %, SOL 0.018 %, DOGE 0.0011 % des Perp-Tagesvolumens. **Ganz ohne
Optionen sind fünf:** ADA, LINK, LTC, DOT, ATOM.

## Handelsjournal — mit dem Zufall neben jeder Serie

Je Trade: **warum er entstand** (Setup, Zeitebene, Rating beim Einstieg, ob er
mit oder gegen den Score ging — alles Felder, die VOR dem Ergebnis geschrieben
wurden), was geschah, und was mechanisch folgt.

> [!warning] Drei Verluste in Folge sind kein Befund
> Bei einer Strategie, die in Wahrheit eine Münze ist, passiert das in **12.5 %**
> der Fälle. 5 in Folge → 3.1 %, 7 → 0.8 %. Darum steht neben jeder Serie ihre
> Zufallswahrscheinlichkeit. Das Projekt hat diesen Fehler schon bezahlt: Setup
> F trug 54 % des Gesamtverlusts über 68 Trades, **E16 fiel trotzdem**
> (+0.0061 R, Intervall über null) — F läuft weiter.

Das Journal schlägt **keine Parameteränderung vor und schaltet nichts ab**.
Eine gescheiterte Hypothese nachträglich zu retten ist die eine Sache, die nie
passieren darf; eine laufende durch eine Verlustserie abzuschalten ist dieselbe
Sache mit umgekehrtem Vorzeichen.

### Der Widerspruch, den das Journal erklärt

Setup B steht bei **+0.372 R im Mittel und −389.91 USD**. Kein Fehler: R ist
risikonormiert, Geld nicht. Aus dem Handelsbuch vom 21.10.:

```
durchschnittliches Risiko  7.75 USD auf Gewinnern
                          17.26 USD auf Verlierern   (Faktor 2.23)
```

Die Verlierer liefen auf grösseren Positionen. Dagegen läuft der 1.5-%-Deckel,
der bei 6 von 20 Trades gegriffen hätte.

## Werkzeuge, Ebenen, Indikatoren

- **17 Zeichenwerkzeuge** wie bestellt (Fadenkreuz bis Lineal), plus Preisalarm
  und „Zeichnungen löschen". Sie merken sich **Zeit und Preis**, nicht Pixel.
- **12 Indikatoren** mit einstellbaren Feldern in einem eigenen Fenster —
  getrennt von *Settings*, wo die Chart-Ebenen an und aus gehen.
- **Ebenen:** FVG, Zonen, Liquidität, Struktur, Trendlinien, Volumen-Näherung,
  Volumenprofil+VPOC, Heatmap, Grosse Trades, Options-Strikes, Positionen,
  plus Kalender und Orderbuch als ausblendbare Seitenteile.

## Betrieb — zwei Stolperstellen

1. **Der Neustart-Wrapper hat ein Budget von 20 Versuchen.** Jeder manuelle
   `Stop-Process` verbraucht einen. Nach dem zwanzigsten gab er auf und das
   Dashboard blieb unten, während die API leere Antworten lieferte — was wie
   ein Codefehler aussah. Zuerst `data/dienst/traidingBrain-dash-plan.log`
   lesen, dann die `.cmd` neu starten.
2. **Der Plan-Dashboard hört auf 8788**, der Live auf 8787.

## Offen

- **Echte Heatmap:** erst gegen die ~46 Tardis-Gratistage messen, ob eine
  sichtbare Wand etwas über die nächsten Minuten sagt. Erst bei einem Ja den
  Dauersammler starten (829 MB/Tag).
- **E22 Trail-Ausstieg** (`audit/E22_TRAIL_VORREGISTRIERUNG.md`), seit E17 frei.
- **Höchstens 2 gleichgerichtete Positionen** (`risk/limits.py`) — die vier
  Stops am 20.10. um 17:13 waren vier Longs in einer Minute.

## Verwandt

[[📡 Datenquellen — was es gibt und was nicht]] · [[📊 Evidenzstand]] ·
[[🧪 Experimentregister]] · [[⚖ Risiko, Hebel & Kapital]] ·
[[🚨 Monitoring & Incidents]] · [[📌 Aktueller Stand]]

## Welche Ebene die Entscheidung sieht — 21.10.2026

Auftrag des Eigentümers: „schaue das alles auch an" (die dreizehn Ebenen-Schalter).
Die Antwort steht im Code und im Register, Ebene für Ebene:

| Ebene im Terminal | Sieht der Einstieg sie? | Geprüft als Prädiktor? | Befund |
|---|---|---|---|
| Fair Value Gaps | **ja** (Setups E, G) | ja, 7'335 Trades | Teil der Null |
| Angebot & Nachfrage (Zonen) | **ja** (Setups E, F; C abgeschaltet) | ja | Teil der Null |
| Liquidität (Pools & Sweeps) | **ja** (Setup A Pools, E Sweep) | ja | Teil der Null |
| Struktur (BOS/CHoCH/Swings) | **ja** (alle Setups) | ja | Teil der Null |
| Trendlinien | **ja** (Setup B) | ja | Teil der Null |
| Volumen-Näherung (aus Kerzen) | nur Volumenschnitt als Indikator | ja (Familie „Volumen" im Score) | trennt nichts |
| Volumenprofil + VPOC (echte Trades) | **nein** | Familie `trades` (aggTrades): 2/4 und 4/4 Linsen gefallen | geschlossen 14.10. |
| Orderbuch-Heatmap | **nein** | Familie `orderbook` (bookDepth, ob500): 4/4, 4/4, 3/4 gefallen | geschlossen 14.10. |
| Grosse Trades (Beträge je Preis) | **nein** | Familie `trades`/`microstructure`: gefallen | geschlossen 14.10. |
| Options-Strikes · Gamma-Last | **nein** | Familie `options` (DVOL, IV-Fläche, Net Buying Pressure): gefallen; **Strike-Abstand selbst nie geprüft**, GEX ohne belegbares Vorzeichen | offen, klein |
| Positionen & Linien | nein (Zeichnung des Nutzers) | — | — |
| Wirtschaftskalender | im Snapshot (`minutes_until`), **nicht** im Einstieg | E12 prüfte Wochenende/Funding-Stunde, **nicht** den Abstand zum Termin | offen, klein |
| Orderbuch (Seitenleiste) | **nein** | wie Heatmap | geschlossen 14.10. |

**Lesart.** Fünf Ebenen sind die Setups selbst. Sechs sind Anzeige aus
Live-Daten, deren Familien am 14.10. über 19 Kandidaten und vier Linsen
als Prädiktoren geschlossen wurden — das Register führt sie unter
`geschlossene_datenfamilien`, damit sie nicht ein zweites Mal gesucht werden.
Zwei Einzelgrössen sind nie als solche geprüft worden: der Abstand zum
nächsten Kalendertermin und der Abstand zum nächsten grossen Strike. Beide
sind Varianten geschlossener Familien („Umlackierung" nach dem Wortlaut des
Registers) und hätten nach der Vorhersage-Nullmessung (35 Merkmale,
Korrelation 0,004) keine hohe Erwartung. Sie lassen sich nur **vorwärts**
messen, weil keine Historie vorliegt: ein Aufzeichner zur Entscheidungszeit,
Wochen Sammelzeit, dann eine Anmeldung mit Schranke. Bis dahin bleibt es dabei:
**keine Ebene schaltet einen Einstieg, die nicht gemessen hat, dass sie etwas
trennt.**

## TradingView-Bedienung — 21.10.2026 (Branch `layout`, Commit `ea884c5`)

Auftrag: „durchsuche komplett TradingView und baue alle Layout-Funktionen
ein, die bei uns nützlich wären". TradingViews Hilfe (Kürzel, Chart-
Einstellungen, Layouts, Zeichenwerkzeuge, Replay, Charttypen) gegen den
Bestand gehalten; alles Nützliche gebaut, jede Gruppe im Browser geprüft.

**Gebaut:** Pfeiltasten/Strg-Zoom/Strg-Rad zum Zeiger/Umschalt-Rad,
Preis- und Zeitachse ziehen, Alt+R, Gehe zu Datum (Alt+G), Zeitebene per
Komma, Strg+K, `?`-Übersicht · Skala Prozent/Log/invertiert/auto ·
Zeitmarke am Fadenkreuz, **Countdown bis Kerzenschluss** (Entscheidungszeit
des Bots), Sitzungswechsel, Hoch/Tief, Gitter, Legende mit Werten am
Fadenkreuz · sieben Charttypen (Heikin-Ashi nur Darstellung, Preisschild
bleibt echt) · Rückgängig/Wiederholen, alle ausblenden, Objektbaum, Magnet,
Umschalt-Einrasten, vertikale Linie, Kreuzlinie, Alt-Kürzel · Seitenleisten
einklappen, Vollbild, Screenshot, Rechtsklick-Menü, Bereichsknöpfe 1T–5J,
**Watchlist**, **Mehrfach-Layout D1/H4/H1/15m** (die Ebenen der Setups,
zeitgekoppelt), **Bar Replay** (Server-Ebenen dort aus — sie kennen die
Zukunft), Vergleich mit zweitem Markt.

**Bewusst nicht:** Renko/Kagi/P&F/Footprint/TPO (zeitlos oder Tick-Daten =
Analyse), Wasserzeichen, Screener/News/Pine, Zeichnung anklicken und
verschieben (Objektbaum + Rückgängig decken es ab). Abweichung von TV: Ziffern
1/2/3 bleiben Ansichtswechsel, Zeitebene über das Komma.

**Geteilter Bereich `api/`:** nur ein lesender Endpunkt
`GET /api/terminal/watchlist`. Dashboard dafür einmal neu gestartet.
