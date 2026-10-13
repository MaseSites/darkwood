# Plan für das 20-Stunden-Fenster, 13.10.2026

Geschrieben **vor** der Arbeit, damit die Reihenfolge begründet ist und nicht
nachträglich erzählt wird.

---

## 0. Was tatsächlich neu dazugekommen ist

Der Auftrag sagt „extrem viele Hilfen heruntergeladen". Nachgesehen statt
vermutet:

| | |
|---|---|
| **firecrawl** (Plugin) | Websuche, Scraping, **Papersuche** über PubMed/arXiv. Echt neu und echt nützlich. |
| **Quiver** (Konnektor) | Finanzdaten: Kongress-Trades, Insider, institutionelle Positionen, Dark Pool. |
| 4 Skills, gestern geprüft | `intended-vs-implemented`, `strategy-red-team`, `deep-research`, `academic-paper-reviewer` |
| Account-Skills | die Anthropic-Standardsammlung (docs, xlsx, pdf, Browser, computer-use …) |

**Trading-spezifische Skills sind keine dabei.** Das ist keine Kritik, nur die
Lage: die neue Fähigkeit ist *Recherche* und *Finanzdaten*, nicht fertige
Strategien.

---

## A. Die Kerzenansicht — zuerst, weil konkret und prüfbar

Der Nutzer hat genau eine Sache benannt, die ihn stört, und sie ist
reparierbar. Diagnose zuerst, damit die Reparatur die Ursache trifft:

| Befund | |
|---|---|
| Der **Positions**-Chart ist nicht der **Vorschlags**-Chart | zwei verschiedene Renderer |
| Positions-Chart | statisches SVG über `innerHTML`, `app.js:2219` |
| Kerzenzahl | **90 fest**, `CHART_CANDLES = 90`, `api/portfolio.py:57` |
| Aktualisierung | alle 15 s komplett neu gezeichnet, `OPEN_POLL_MS` |
| Zoom, Schwenken, Fadenkreuz | **keines** |

Der Vorschlags-Chart (`chart.js`, 22 KB) hat Interaktion und
Risiko/Chance-Flächen. Der Positions-Chart hat davon nichts.

### A1. Was NICHT angefasst wird, und warum

`chart.js` dokumentiert im Kopf eine absichtliche Eigenschaft:

> „THE CHART STOPS AT THE DECISION. A chart running to the present shows the
> reader what happened next, and then there is nothing left to judge."

Für einen **Vorschlag** ist das eine Integritätseigenschaft: man soll ihn
ohne Rückschau beurteilen. Sie wird nicht ersetzt. Eine Bibliothek, die bis
zur Gegenwart zeichnet, würde genau diese Eigenschaft stillschweigend
aufheben.

### A2. Was gebaut wird

Für **laufende Trades** gilt das Gegenteil: dort *muss* man sehen, wo der
Kurs jetzt steht. Also ein echter interaktiver Chart, und zwar mit
**`lightweight-charts`** — der Open-Source-Charting-Bibliothek von
TradingView selbst (Apache-2.0).

Das ist die ehrliche Antwort auf „verbinde dich mit TradingView": kein
API-Schlüssel, keine Anmeldung, keine Abhängigkeit von einem fremden Dienst
zur Laufzeit, und es ist dieselbe Engine, die TradingView benutzt. Die
Bibliothek wird **mitgeliefert**, nicht von einem CDN geladen — eine fertige
Seite darf nicht von einem fremden Host abhängen.

Was dazukommt, und jedes Stück beantwortet einen Teil der Beschwerde:

1. **Zoom und Schwenken.** Heute 90 Kerzen, nicht mehr und nicht weniger.
2. **Fadenkreuz mit OHLC-Anzeige** an der Mausposition.
3. **Einstiegsmarke** — wo genau sind wir rein, sichtbar und nicht nur als
   Zeitstempel.
4. **Preislinien** für Entry, Stop, Ziel, als erstklassige Objekte der
   Bibliothek statt als gezeichnete Linien.
5. **Zeitebenen-Umschalter** — derselbe Trade auf M15, H1, H4.
6. **Letzter Kurs live**, ohne den ganzen Chart neu zu zeichnen.

### A3. Abnahme

Im Browser geprüft, mit Bildschirmaufnahme: ein laufender Trade, Zoom
hinein, Fadenkreuz auf eine Kerze, Einstiegsmarke sichtbar, drei Preislinien
auf den Werten aus dem Journal. Keine Konsolenfehler, keine Netzabhängigkeit.

---

## B. Die Wächter — weil „mach keine Fehler" Maschinerie braucht

Der Auftrag sagt „mach keine Fehler". Das kann ich nicht versprechen, und ein
Versprechen wäre die unehrlichere Antwort. Was ich sagen kann:

**Heute habe ich mehrere Fehler gemacht, und jeden einzelnen hat ein Wächter
gefangen**, nicht ich:

| Fehler | wer ihn fand |
|---|---|
| `intent.signal_timeframe` existiert nicht auf dieser Klasse | der Live-Golden-Test, mit Absturz |
| Mein Runner umging die Konfiguration | der Rauchtest vor dem Sechsstundenlauf |
| Der Backfill-Fix war auf halber Strecke stehengeblieben | der nächste Lauf, der daran starb |
| Ein Quelltext-Wächter scannte **nichts** und war grün | ich, weil ich nachgesehen habe, was er findet |
| Die Buchabstimmung passte nach der Umstellung nicht mehr | der Wächter selbst, mit „12 statt 1" |
| Signatur-Stub ohne das neue Feld | `test_the_signature_format_is_frozen` |
| `Rule.LIMITS` ohne Test | `test_every_rule_is_reachable` |

Daraus folgt die Priorität: **nicht fehlerfrei arbeiten, sondern die Zahl der
Fehler senken, die unbemerkt bleiben.** Konkret in diesem Fenster:

- Den laufenden `intended-vs-implemented`-Audit über die vier Geldgrenzen
  auswerten und anwenden, was die Gegenprüfung übersteht.
- Für jeden Befund beide Seiten zitieren — Dokumentation mit Zeile, Code mit
  Zeile. Das ist die Methode aus dem neuen Skill, und sie ist strenger als
  das, was ich bisher getan habe.
- `SAFETY_RULES` ist zweimal mit verschiedenem Inhalt definiert
  (`RISIKO_AUDIT_NACHPRUEFUNG.md` 2.6). Das ist eine Messfrage, keine
  Aufräumarbeit — sie wird gestellt, nicht stillschweigend entschieden.

---

## C. Recherche — mit firecrawl, aber ehrlich eingeordnet

Der Auftrag will „das komplette Internet durchsuchen" und eine Datenbank der
besten Strategien.

**Die Lage, bevor ich suche.** 124 Registereinträge sind gelaufen. 32 Agenten
haben 24 Literaturansätze geprüft, **null** haben die gegnerische Prüfung
überlebt. Und gemessen am Versuchsbudget tragen fünf Jahre Daten etwa 45
unabhängige Versuche — die Suche hat die Datenlänge längst überholt.

Daraus folgt nicht „nicht suchen". Es folgt, **wonach** zu suchen ist:

* **Nicht** eine weitere Strategie für dieselben zwölf Märkte. Der 125.
  Versuch auf denselben Daten ist statistisch wertlos.
* **Sondern** Ansätze, die Daten brauchen, die wir *nicht* haben — und dann
  die Frage, ob diese Daten beschaffbar sind. Orderbuch-Tiefe,
  Liquidationskaskaden, Perp-Basis gegen Spot, Funding-Termstruktur,
  Optionsdaten. Das ist der einzige Weg, der die Schranke von ±0,09 R
  verschieben kann.
* Dazu: `firecrawl_research_search_papers` über arXiv — eine echte
  Papersuche, nicht Blogposts.

Jeder Kandidat wird in `audit/EXPERIMENTS_NEXT.yaml` angemeldet, **bevor** er
gerechnet wird, und erhöht `total_comparisons`. Ohne das ist jede Korrektur
eine Erzählung.

---

## D. Daten — der einzige Hebel, der die Statistik bewegt

41 von 83 Märkten liegen. Funding für alle 83. Der Rest wird nachgeholt, und
danach läuft der Replay über die grössere Menge.

Das ist unspektakulär und es ist der wirksamste Punkt dieses Plans: die
Schranke [−0,0868; +0,0594] R stammt von zwölf Märkten. 83 Märkte sind nicht
sieben Mal so viel Beweis — Krypto bewegt sich als Block —, aber es ist der
einzige Posten, der sie überhaupt verschieben kann.

---

## E. Handeln — schon umgestellt, und mehr wäre keine Verbesserung

Seit heute: eine Kasse mit 12.075 USDT statt zwölf mit je 1.006, Risiko
120,76 statt 10,06 USDT je Trade. Das war der Wunsch und er ist erfüllt.

**„Noch mehr Trades" ist kein offener Punkt, sondern ein gemessener.** Mehr
Trades heissen lockerere Filter, und das ist mehrfach geprüft: die
Trefferquote ist ein irreführendes Ziel, die Einstiege tragen keinen Vorteil,
und ein Hebel, der nur die Trade-Zahl ändert, kann das Vorzeichen nicht
drehen. Was die Trade-Zahl wirklich hebt, ohne eine Regel zu lockern, sind
mehr **Märkte** — siehe D.

---

## Reihenfolge

1. **A** — die Kerzenansicht. Konkret, geprüft im Browser, vom Nutzer benannt.
2. **B** — den Audit auswerten und anwenden.
3. **D** — Backfill zu Ende, Replay über die grössere Menge.
4. **C** — Recherche, auf die Frage „welche Daten fehlen uns" gerichtet.

A und D laufen parallel: der Backfill ist Netz, der Chart ist Code.

## Was in diesem Fenster nicht passiert

* Keine Schutzregel wird gelockert, um mehr Trades zu erzeugen.
* Kein Erfolgskriterium wird nach dem Ergebnis geändert.
* Keine Zahl ohne ihr Intervall.
* Kein Einzelmarkt als Eigenschaft des Systems.
* Beide Tore bleiben: korrigiertes Intervall ohne Null **und** Replikation
  0,5–2,0×.
* Kein API-Budget für Modellaufrufe im Backtest.
