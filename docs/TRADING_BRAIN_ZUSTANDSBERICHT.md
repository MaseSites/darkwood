# traidingBrain — vollständiger Zustandsbericht

**Stand:** 2026-10-06, 16:18 UTC · **Commit:** `f0f1719` · **Branch:** `freqtrade-core`
**Zweck dieser Datei:** Grundlage für eine externe Recherche. Sie soll jemandem, der das
Projekt nicht kennt, erlauben, Lösungen, Verbesserungen und neue Ideen zu finden, ohne
erst Fragen stellen zu müssen.

---

---

## 0a. Was sich am 07.10.2026 geändert hat — bitte zuerst lesen

Eine externe Recherche (`TRADING_BRAIN_CLAUDE_RECHERCHE_UND_UMBAUPROMPT.md`) hat acht
Aussagen dieses Berichts bestritten. **Jede wurde mit Code oder Handrechnung geprüft, und
vier davon trafen zu.** Der volle Nachweis steht in `audit/RECHERCHE_KORREKTUREN.md`; hier
die Kurzfassung, weil die betroffenen Abschnitte unten sonst in die Irre führen.

| Was hier stand | Was gilt | Abschnitt |
|---|---|---|
| „Eine Auswahl unter Einträgen ohne Vorteil kann nichts beitragen" | **Falsch.** Kategoriefehler. Pool −0,0906 R, Teilmenge `rating_band=eindeutig` **+0,0311 R**, beides ex ante bekannt. Und das Projekt hatte drei Tage vorher Setup C auf genau dieser Grundlage abgeschaltet. | 6.4 |
| „Stop, Positionsgrösse und Hebel kürzen sich heraus" | Grösse und Hebel ja, **der Stop nicht.** Er verschiebt den Ausstieg: ein 1,5× weiterer Stop hätte **70,1 %** der ausgestoppten Trades nicht beendet. | 3.1 |
| „Keine Gebührensenkung kann das Vorzeichen drehen" | **Nur für diese Börsenfamilie.** An Primärquellen und an den Marktdaten der Venue selbst geprüft: 0 % Maker **und** 0 % Taker existieren. Gemessener Taker/Taker-Round-Trip auf BTC bei 1 000 USD: **0,0005 %** — 22× unter der Obergrenze des gemessenen Vorsprungs. | 4.2, 11.1 |
| „BNBUSDT-Funding ist kaputt (49,6 % Nullen)" | **Die Nullen sind echt** (73/73 auch bei der Venue, `observed_zero`). Der Ausschluss war ein Fehler. Der wirkliche Defekt ist grösser: **das Funding-Verzeichnis mischt zwei Börsen** — 4 Bybit, 8 Binance. | 8.1, 9.1 |
| „FreqAI hat kein Purging und kein Embargo" | **Zu grob.** Training → Vorhersage ist sauber (der Shift schützt sich selbst). Training → **interne Validierung** leckt, und das ist die Grenze, an der Early Stopping hängt. `test_size` steht jetzt auf 0. | 9.3 I9 |

**Neu gemessen, und es ist das erste Mal positiv:** Die offene Frage zum Kostendeckel ist
beantwortet. Über 12 Märkte und 43 727 Signale haben billige Trades **besseres Brutto**
(+0,0561 R, Intervall **[+0,017; +0,097]**, Null ausgeschlossen), nicht nur weniger Maut. Es
ist trotzdem **kein Vorteil**: R je Trade liegt bei +0,0107 mit [−0,041; +0,061].

**Zwei weitere Scheinfunde gefangen, der zweite der grösste bisher:** ein `max_adverse_r`
von bis zu 147,88 R, das Kursbewegung **nach dem Ausstieg** mitzählte (25,3 % der
ausgestoppten Trades betroffen), und ein Ridge-Modell, das **+1018 %** meldete, weil seine
Merkmale die Kerze kannten, die sie handeln (Korrelation zum Ziel **+0,9999**; um eine Kerze
verschoben: −0,0059).

**Neue Lieferungen:** `audit/RECHERCHE_KORREKTUREN.md` · `audit/EXPERIMENTS_NEXT.yaml`
(E0–E7 vorab registriert, 46 Vergleiche) · `audit/DATEN_MANIFEST.yaml` ·
`audit/TARGET_20X_REPORT.md` · `audit/VENUE_KOSTEN_REPORT.md`

**Neues Ziel:** 1 000 CHF → 20 000 CHF bis 07.04.2027. Bei 413 Trades und 3 % Risiko
verlangt das **+0,243 R je Trade**, also eine Trefferquote von 44,3 % gegen gemessene
32,5 %. Anders als beim alten Ziel ist das **nicht** mehr als das physikalisch Mögliche —
es ist unbelegt, nicht unmöglich. Zielchance auf der gemessenen Verteilung: **0,00 %**.

---

## 0. Wie diese Datei zu lesen ist

Jede Aussage trägt eine Kennzeichnung:

| Marke | Bedeutung |
|---|---|
| **[GEMESSEN]** | In diesem Projekt gerechnet, mit Skript und Datenbasis. Nachvollziehbar über den genannten Befehl. |
| **[FAKT]** | Nachprüfbare Eigenschaft des Systems, der Umgebung oder der Daten. Keine Statistik, sondern Inventar. |
| **[VERMUTUNG]** | Nicht gemessen. Plausibel, aber unbelegt. **Jede solche Zeile ist ein Rechercheauftrag, keine Grundlage.** |
| **[ENTSCHEIDUNG]** | Eine Festlegung mit Begründung, keine Messung. Kann überdacht werden. |
| **[OFFEN]** | Bekannte Lücke. |

**Eine Bitte an die Recherche:** Die wichtigste Eigenschaft dieses Projekts ist, dass es
Scheinfunde fängt, bevor sie geglaubt werden (Abschnitt 7). Ein Vorschlag, der diese
Schutzvorrichtungen umgeht — etwa „probier einfach Parameter X" oder „nimm das Modell mit
der besten Testfenster-Zahl" — ist für dieses Projekt wertlos, auch wenn er anderswo
funktioniert. Abschnitt 12 listet die Regeln, die ein brauchbarer Vorschlag respektieren muss.

---

## 1. Was das System ist

**[FAKT]** Ein Forschungs- und Handelsvorbereitungssystem für Kryptowährungs-Perpetuals.
Leitidee: Ein LLM ist **ausschliesslich Interpretationsschicht**, nie Datenquelle und nie
Executor. Daten kommen deterministisch aus Code, ausgeführt wird erst nach menschlicher
Bestätigung.

Der Ablauf, den das System vorbereitet:

```
Marktdaten (Parquet)
  → Analyse (Indikatoren, Struktur, Liquidität, Regime, Zonen)
  → Setups (6 regelbasierte Muster, 5 aktiv)
  → Risikoschicht (5 Regeln; jede kann ablehnen)
  → Vorschlag (Entry, Stop, Ziel, Hebel, Grösse, Risiko in CHF)
  → [MENSCH bestätigt 1,2 s gedrückt]
  → Order
```

**[FAKT]** Der letzte Pfeil existiert heute nur als Code gegen Testnet. Es wird kein echtes
Geld gehandelt.

**Grösse des Projekts [FAKT]:**

| | |
|---|---|
| Python-Dateien | 274 |
| Codezeilen (src + scripts + tests) | 71 559 |
| Tests | **1 462** in 76 Dateien, alle grün (`PYTEST_EXIT=0`) |
| Commits | 165 |
| Datenbestand auf Platte | 867 MB, 521 Parquet-Dateien |
| Linter | `ruff` über `src/ tests/ scripts/` sauber |

---

## 2. Harte Randbedingungen — nicht verhandelbar

**[FAKT]** Diese Punkte sind vom Nutzer gesetzt und stehen über jedem Optimierungsvorschlag.
Eine Empfehlung, die einen davon verletzt, ist unbrauchbar.

1. **Das System darf nichts selbst handeln, aber alles vorbereiten.** Jede echte Order
   braucht eine 1,2 Sekunden gehaltene menschliche Bestätigung.
2. **Der Kontoinhaber ist unter 18.** Börsen verlangen 18+. Keine Umgehung. Wird ein
   Erwachsenenkonto genutzt, muss **dieser Erwachsene** den Bestätigungsknopf halten.
3. **API-Schlüssel: Handelsrecht ja, Auszahlungsrecht niemals.**
4. **Secrets nur in `.env` / gitignorierten Dateien.** Nie im Repo, nie im Obsidian-Vault.
5. **Live-Handel braucht zwei unabhängige Signale** (`testnet=False` UND `allow_live=True`).
6. **Tests laufen nie gegen die Produktions-Postgres-Datenbank.**
7. **Der MCP-Adapter bekommt keine Werkzeuge für echte Orders**, keine beliebigen
   Shell-Kommandos und keine freien Dateipfade aus Werkzeugargumenten.
8. **Kein höherer Hebel als Ersatz für einen fehlenden Vorteil.**
9. **Kein negativer Befund, der als Erfolg verkauft wird.**

---

## 3. Das Ziel und seine Arithmetik

**[FAKT]** Das stehende Ziel: **12 000 CHF → 15 000 CHF bis zum 30.10.2026** im Papierhandel.

**[GEMESSEN]** `python scripts/goal.py`, Stand 06.10.2026:

```
Ziel        15,000 CHF bis 30.10.2026
Stand       12,004.28 CHF   -> fehlen 2,995.72 CHF (+25.0%)
Tage        24
Takt        2.27 Trades/Tag, vorwärts gemessen -> 55 Chancen bis zur Frist
Risiko      10.00 CHF pro Trade = 0.0833% des Portfolios (Deckel 1.0%, hart 3.0%)

NÖTIG       +4.92 R pro Trade
MAXIMUM     +2.15 R pro Trade  (mittleres geplantes Chance-Risiko aus 2 734 Trades,
                                also wenn JEDER Trade sein Ziel trifft und keiner
                                seinen Stop)
```

**Das Ziel verlangt bei diesem Risiko das 2,3-fache des physikalisch Möglichen.** Das ist
keine Einschätzung, sondern eine Division: Mit 55 verbleibenden Gelegenheiten, 1 % Risiko und
einem mittleren geplanten Chance-Risiko-Verhältnis von 1 : 2,15 ist die Obergrenze erreicht,
bevor das Ziel beginnt.

### 3.1 Die Formeln, die alles tragen

**[FAKT]** Diese Gleichungen sind der Kern des Projekts und widerlegen eine ganze Klasse von
Verbesserungsideen:

```
net_r = (eingefangene Bewegung − Gebühr) / Stop-Abstand
```

**Positionsgrösse und Hebel kürzen sich heraus.** Jeder Vorschlag der Form „mehr Hebel" oder
„grössere Positionen" ist damit arithmetisch erledigt — er verändert die Zahl nicht, nur ihre
Streuung.

> **Korrektur vom 07.10.2026.** Hier stand, der **Stop** kürze sich ebenso heraus. Er tut es
> nicht. Er steht im Nenner **und verschiebt den Ausstieg**, also den ganzen Pfad. Gemessen
> über die 1 858 ausgestoppten Replay-Trades (`python scripts/study_stop_path.py`): ein Stop
> 1,5× so weit hätte **70,1 %** von ihnen nicht beendet, 94,2 % waren vorher im Plus, 52,8 %
> davon um mehr als +0,5 R. Die Annahme „gleicher Pfad" ist für die Mehrheit der Trades
> falsch.
>
> Die korrekte Fassung: bei **festem Pfad** ändert ein anderer Stop nur den Nenner und nicht
> das Vorzeichen des Zählers. Sobald der Stop den Ausstieg verschiebt, ist der Pfad nicht mehr
> fest. „Engerer Stop, gleiche Bewegung angenommen" bleibt widerlegt; „anderer Stop, Pfad neu
> simuliert" ist eine zulässige Studie und heisst **E3**.

Was das Vorzeichen ändern kann, bleibt zweierlei: mehr eingefangene Bewegung, oder eine
niedrigere Gebühr. **Und der zweite Weg war zu eng gefasst** — siehe 4.2 und 11.1: die
0,0400 % sind der Boden *dieser* Börsenfamilie, nicht des Marktes.

```
nötige Trefferquote  p = (1 + Maut/Bewegung) / 2
Zielrendite          n · [p·ln(1+f·w) + (1−p)·ln(1−f·l)] = ln(G)
```

**[GEMESSEN]** Gemessene Auszahlung aus 2 734 Journal-Trades: **+1,816 R gewonnen /
−1,008 R verloren** (1 : 1,802), Trefferquote **32,48 %**, Erwartung **−0,0906 R**.

| Risiko/Trade | nötiges R | nötige Trefferquote | Lücke |
|---|---|---|---|
| 0,5 % | +0,8191 | 64,86 % | +32,4 Pp |
| 1,0 % | +0,4095 | 50,55 % | +18,1 Pp |
| 2,0 % | +0,2048 | 43,63 % | +11,2 Pp |
| 3,0 % | +0,1365 | 41,54 % | +9,1 Pp |

**[FAKT] Jensen:** `E[ln(1+fR)] < ln(1+f·E[R])`. Geschlossene Formeln mit konstantem R sind
daher **optimistische Untergrenzen**, nie Schätzungen. Bei 1 % Risiko und gemessener
Trefferquote: konstantes R sagt 11 425 CHF, die echte R-Streuung derselben Trades sagt
**11 364 CHF**.

### 3.2 Ein Fehler in diesem Projekt, der genau hier sass

**[GEMESSEN]** Früher stand hier „56,6 % Trefferquote reichen für 20×". Das war falsch: Die
Zahl setzte stillschweigend Gewinner von +1,371 R voraus. Bei symmetrischem ±1 R braucht 20×
**66,75 %**, und 56,6 % erreichen nur **2,99×**. Mit der tatsächlich gemessenen Auszahlung
sind es **61,8 %**.

**Lehre, die in Code gegossen wurde:** `learn/target.py` kann eine Trefferquote nicht mehr
ohne Auszahlungsschema berechnen, und `payout_implied_by()` holt aus jeder gemeldeten Quote
die verschwiegene Annahme heraus.

---

## 4. Der zentrale Befund: die Maut ist grösser als jeder gefundene Vorteil

Dies ist das wichtigste Ergebnis des gesamten Projekts.

### 4.1 Unabhängige Bestätigung durch fremden Code

**[GEMESSEN]** Freqtrade 2026.9 (fremde Codebasis), Binance Spot, eine schlichte
EMA-Trend-Strategie, 2025-03-01 bis 2026-09-30, BTC/ETH/SOL, 5-Minuten-Kerzen:

```
15 624 Trades, 83 Wochenblöcke

brutto (reine Preisbewegung)   +0.0147%  [+0.0051, +0.0244]
Maut   (Gebühren)              +0.1998%
netto  (gebucht)               -0.1852%  [-0.1947, -0.1754]
```

Reproduzierbar: `python scripts/ft.py --measure backtesting --strategy BaselineTrend
--timerange 20250301-20261001` dann `python scripts/study_freqtrade_gross.py`.

### 4.2 Die entscheidende Messung: Vorsprung gegen einen ahnungslosen Einstieg

**[FAKT]** Alle Trades sind long, Spot, Hebel 1. Die Bruttorendite **ist** also die
Marktbewegung über das Haltefenster; die Strategie wählt nur, **wann** das Fenster beginnt.
„Gegen null messen" fragt nur, ob Krypto gestiegen ist. Richtig ist: gegen das, was ein
ahnungsloser Einstieg gleicher Länge im selben Markt und Zeitraum eingefahren hätte.

**[GEMESSEN]** Horizont wird vom Messskript vorgegeben, nicht vom Trade:

| Horizont | Basis (ahnungslos) | Vorsprung des Einstiegs | 95 %-Intervall |
|---|---|---|---|
| **5 min** | +0,0002 % | **+0,0070 %** | **[+0,0035, +0,0106]** ✱ |
| 25 min | +0,0009 % | +0,0075 % | [−0,0009, +0,0158] |
| 60 min | +0,0021 % | +0,0092 % | [−0,0052, +0,0238] |
| 240 min | +0,0083 % | +0,0092 % | [−0,0403, +0,0593] |

Nur eine von vier Zellen schliesst die Null aus, und es ist die kürzeste.

**[GEMESSEN] Die Entscheidung:**

```
Obergrenze der einzigen belegten Zelle   0.0106%
Maut maker/maker (physikalischer Boden)  0.0400%
Maut maker/taker (realistisch)           0.0750%
Maut dieses Spot-Laufs                   0.1998%

Es fehlt der Faktor 3.8
```

Und zwar **nach drei Zugeständnissen**: günstigste Zelle gewählt, keine Mehrfachkorrektur
angewandt, oberer Rand des Intervalls genommen. Alle drei zusammen reichen nicht.

**Daraus folgt [FAKT], und zwar für diese Börsenfamilie:** Eine Gebührensenkung *innerhalb*
dieser Struktur kann nur einholen, was an Vorsprung da ist, und es ist weniger Vorsprung da
als ihre billigste Gebühr.

> **Korrektur vom 07.10.2026.** Hier stand der Satz ohne Einschränkung: *„Jeder Vorschlag,
> der nur die Kosten senkt, kann das Vorzeichen nicht drehen."* Das ist eine Aussage über
> **alle** Börsen, gezogen aus einer Messung auf **einer**.
>
> An den Primärquellen abgerufen und zusätzlich **an den Marktdaten der Venue selbst**
> nachgemessen: 0 % Maker und 0 % Taker existieren. Und was eine Ausführung dort wirklich
> kostet, gemessen als Walk durchs Buch für eine echte Ordergrösse
> (`python scripts/study_venue_cost.py`), Median aus fünf Stichproben, Taker rein und raus
> bei 1 000 USD:
>
> | Markt | Runde | gegen den Vorsprung (0,0106 %) |
> |---|---:|---|
> | **BTC** | **0,0005 %** | **22× darunter** |
> | ETH | 0,0054 % | 0,51× darunter |
> | SOL | 0,0059 % | 0,56× darunter |
> | XRP | 0,0146 % | 1,38× darüber |
> | LINK / DOGE | 0,0339 / 0,0379 % | 3,2× / 3,6× darüber |
>
> Auf der bisherigen Börse lag der **Boden** 3,8× *über* dem Vorsprung. Das ist die erste
> Messung in diesem Projekt, in der die Gesamtkosten einer Venue darunter liegen.
>
> **Was daraus nicht folgt: dass es geht.** Der Vorsprung wurde auf 5-Minuten-Kerzen einer
> anderen Börse gemessen. Ein dort gemessenes Signal wird nicht dadurch zu einem hier
> belegten, dass die Ausführung billiger ist. Gezeigt ist: die Maut ist nicht mehr der Grund,
> warum es nicht gehen kann. Offen ist: ob es geht. Das ist **E0**, erste Priorität, und
> `audit/VENUE_KOSTEN_REPORT.md` listet die sechs Schritte, die noch fehlen.

### 4.3 Zwei Methodenfallen, die auf dem Weg dorthin lagen

**[GEMESSEN] Falle 1 — die Haltedauer ist vom Ausgang gewählt.** Korrelation Haltedauer ↔
Bruttorendite: **+0,519**. Gewinner laufen bis zum Gewinnziel (Median 115 min), Verlierer
werden am EMA-Bruch gekappt (Median 20 min). Eine Vergleichsgrösse auf die *realisierte*
Dauer zu stützen heisst, auf das Ergebnis zu bedingen — der Vergleich erbt dann seine eigene
Antwort. Deshalb gibt das Skript den Horizont vor.

**[GEMESSEN] Falle 2 — eine Einheitenverwechslung machte die Vergleichsgrösse still null.**
`pandas` 3 wählt die Zeiteinheit pro Datei. `.astype("int64")` liefert die *gespeicherte*
Einheit. Eine Division durch eine Million erzeugte Kilosekunden, wodurch jeder
Zeitstempelvergleich falsch war, die Vergleichsscheibe **leer** und die Basis exakt
`+0,0000 %` — was den Vorsprung echt aussehen liess. Korrekt ist
`.dt.as_unit("ms").astype("int64")`, und der Verbraucher **weigert sich** jetzt, ein leeres
Fenster zu mitteln, statt es stillschweigend als null zu behandeln.

---

## 5. Zustand in Zahlen

### 5.1 Papierhandel (die einzige Vorwärts-Evidenz)

**[GEMESSEN]** `python scripts/papertrade.py --status`:

| | |
|---|---|
| Kapital | **12 004,28 CHF** über 12 Konten à 1 000 |
| Vorwärts-Trades im Journal | **8** |
| Mittel | **−0,112 R**, Trefferquote 38 % |
| Zeitraum | 02.10.2026 08:00 bis 05.10.2026 20:32 |
| Takt | 2,27 Trades/Tag |

**[GEMESSEN]** Annahmequote der Risikoschicht über alle 12 Konten: **54 Vorschläge auf
1 320 ausgewertete Kerzen, 46 abgelehnt, 8 eröffnet = 14,8 %.**

**[FAKT] Eine strukturelle Eigenschaft, die man von aussen nicht sieht und die für die
Zielrechnung entscheidend ist:** Es sind **zwölf getrennte Konten à 1 000 CHF**, nicht ein
Konto über 12 000. Das Risiko pro Trade ist 1 % **eines Kontos** = **10,00 CHF**, also nur
**0,0833 % des Gesamtkapitals**. Dazu kommt `max_open_positions: 2` — zu keinem Zeitpunkt
stehen mehr als **20 CHF von 12 004 CHF** im Risiko, das sind **0,17 %**.

Daraus folgt direkt die Zahl aus 3: Um 25 % in 55 Gelegenheiten zu schaffen, braucht es bei
0,0833 % Einsatz **+4,92 R je Trade**. Bei einem einzigen 12 000-CHF-Konto mit 1 % Risiko
wären es **+0,41 R** — immer noch weit über dem gemessenen −0,034 R, aber ein ganz anderes
Bild. **Das ist eine Architekturentscheidung, keine Messung**, und sie gehört zu den Dingen,
die eine Recherche prüfen sollte (siehe F18).

### 5.2 Journal gesamt

**[GEMESSEN]** 2 742 Trades: **8 `live`** (vorwärts), **2 734 `replay`**.
Die beiden werden **nie gemischt** — ein Replay-Trade kennt sein Fenster im Nachhinein, ein
Vorwärts-Trade nicht.

### 5.3 Signal-Sammlung (laufend)

**[GEMESSEN]** Unter der aktuellen Konfigurationssignatur (Kostendeckel 0,08):
**6 von 12 Märkten, 19 328 Signale** (läuft weiter). Aufschlüsselung der Ablehnungen,
Stand 17 676 Signale:

| Ablehnende Regel | Signale | Anteil |
|---|---|---|
| `kosten` (Kostendeckel) | 8 758 | 49,5 % |
| `chance_risiko` | 6 499 | 36,8 % |
| *genommen* | 2 417 | 13,7 % |
| `liquidation` | 2 | 0,01 % |

### 5.4 Das Forschungsregister

**[GEMESSEN]** `python scripts/ratchet.py`:

```
124 Versuche im Register, 87 verschiedene Arme
34 davon in R gemessen und damit mit dem Champion vergleichbar
0 davon aus dem Prüffenster

KEIN BELEGTER VORTEIL
```

Champion: `heutige_konfiguration` mit **−0,0340 R** über 3 300 Trades.

---

## 6. Inventar — was gebaut ist

### 6.1 Eigenes Paket `src/traidingbrain/`

**[FAKT]** 19 Teilpakete:

| Paket | Inhalt |
|---|---|
| `domain/` | Pydantic-Typen und Protokolle: `DataSource`, `Broker`, `Clock`, `SymbolSpec`, `MarketSnapshot`, `Verdict` |
| `data/` | Börsenanbindung (ccxt), Backfill, Parquet-Speicher, Validierung, Funding, Derivate, Flow, externe Quellen, Kalender |
| `analysis/` | Indikatoren, Struktur (Swings/BOS/CHoCH), Liquidität, FVG-Qualität, Regime, Zonen, Trendlinien, Sessions, Positionierung, Multi-Timeframe-Snapshot |
| `strategy/` | 6 Setups, 5 aktiv (s. 6.5) |
| `risk/` | Sizing, Hebel, Limits |
| `sim/` | Broker (Fills, Gaps, Gebühren, Funding, Liquidation), Engine, Metriken, `plan.py` (die 5 Risikoregeln) |
| `learn/` | Labels, Features, Modelle, Splits (purged/embargoed), Register, `target.py`, `panel.py`, `outlook.py` |
| `brain/` | LLM-Schicht: Schema, Prompt, Client, Guard, Scoring, Cache, Postmortem, FakeBrain |
| `live/` | Papierhändler, Zustandspersistenz, Loop |
| `execution/` | Order, Intent, Reconcile, Watchdog, Diagnose |
| `journal/` | Trade-Journal, Signal-Speicher, Postmortem, Versionierung |
| `adapter/` | MCP-Server, Jobs-Registry, Argumentvalidierung |
| `api/`, `dashboard/` | FastAPI + Jinja/HTMX-Oberfläche |
| `history/` | kNN-Ähnlichkeitssuche mit Purging/Embargo |
| `score/`, `reporting/`, `storage/`, `proposals/`, `config/` | Bewertung, Intervalle, Postgres, Vorschlagsspeicher, Konfiguration |

### 6.2 Freqtrade als zweiter, unabhängiger Kern

**[FAKT]** Native Installation in `freqtrade/.venv` (kein Docker nötig):

```
Python 3.14.2 · freqtrade 2026.9 · TA-Lib 0.8.1
LightGBM 4.7.0 · XGBoost 3.4.1 · scikit-learn 1.9.1
```

Konfigurationskette (`scripts/ft.py` erzwingt sie):
`config.base.json` → `config.freqai.json` (optional) → `config.local.json` (gitignoriert) →
`config.measure.json` (optional, zuletzt, gewinnt).

Strategien: `BaselineTrend` (fester Massstab), `FreqaiCostFiltered` (ML-Eintritt mit
Kostenfilter).

### 6.3 MCP-Adapter

**[FAKT]** 12 Werkzeuge, davon die drei vom Forschungsauftrag benannten:
`get_system_status`, `list_strategies`, `download_market_data`, `run_backtest`,
`get_job_status`, `stop_job`, `get_backtest_report`, `get_paper_portfolio`,
`get_trade_journal`, **`get_data_coverage`**, **`run_horizon_experiment`**,
**`get_experiment_report`**.

Sicherheitseigenschaften **[FAKT]**: `echte_orders_moeglich: False`; Allowlists für Paare,
Zeitrahmen, Modelle, Feature-Gruppen, Horizonte; ein Strategiename wird gegen ein
Verzeichnis-Scan geprüft und **wird nie zu einem Pfad**; ein Job zur Zeit; Dubletten über
SHA-256 des Befehls; Log in eine **Datei**, nicht in eine Pipe (ein Kind, das mehr schreibt
als der Pipe-Puffer fasst, würde sonst ewig blockieren).
**65 feindliche Tests** über `validate.py` und `jobs.py`.

### 6.4 Die LLM-Schicht — Zustand

**[FAKT]** Gebaut, aber **im Forschungsregister praktisch unbenutzt**. Vorhanden:

- Normalisierter Snapshot: Das Modell sieht **keine absoluten Preise, kein Datum, keinen
  Symbolnamen** — alles in ATR-Einheiten plus benannte Level-IDs (`lvl_3: swing_low`). Das
  Verdikt liefert `entry_anchor: LevelId` + `offset_atr`, Python löst zu Preisen auf.
  **Preis-Halluzination wird dadurch strukturell unmöglich**, und das Modell kann aus
  „BTC, 16 540 $, extreme Vola" nicht mehr November 2022 erkennen und sein Wissen über den
  Kursverlauf danach einfliessen lassen — ein Lookahead, den **kein Code-Test finden kann**.
- Gewichtete Confidence rechnet **Python**, nicht das Modell: Es liefert pro Faktor einen
  Score −1…+1 mit Begründung, Python bildet die gewichtete Summe (Struktur 30 %,
  Indikatoren 25 %, Liquidität 20 %, News 15 % → **auf 0 gesetzt**, History 10 %).
- Decision-Cache als **einzige** Reproduzierbarkeitsgarantie (Sampling-Parameter existieren
  auf diesen Modellen nicht). Cache-Key:
  `sha256(kanonisches_snapshot_json + prompt_version + model_id + schema_version)`.
- Guard mit Property-Tests, `FakeBrain` für netzlose Testläufe (`pytest-socket`),
  Zwei-Stufen-Trigger, Postmortem.
- Konfiguriert: `claude-opus-5-5` für Entscheidungen, `claude-sonnet-5-5` für
  Prompt-Iteration.

**[GEMESSEN]** `scripts/study_brain_judge.py` fragt eng: *Ist das Urteil etwas wert, wenn
Entry, Stop und Ziel unverändert bleiben?* Der Standard-Richter ist bewusst der arithmetische
`FakeBrain` — ein echtes Modell muss **diese** Linie schlagen, nicht den ungefilterten Pool.
Stand der Datei `data/study_brain_judge.json`: BTCUSDT, Arm „ohne Urteil" 3 Trades, Arm „mit
Urteil" **0 Trades bei 30 Vetos**. **Zu wenig für eine Aussage.** [OFFEN]

**[FAKT] Warum die LLM-Schicht im Register kaum vorkommt:** Die Reihenfolge des Projekts ist
Daten → Herkunft → Basisrate → Modell. Die Brutto-Erwartung der genommenen Einträge ist
**−0,0102 R [−0,070, +0,051]**, also nicht von null zu trennen, und solange das so ist, ist
der günstigere Massstab für ein Urteil der arithmetische `FakeBrain` und nicht der
ungefilterte Pool.

> **Korrektur vom 07.10.2026.** Hier stand: *„kann eine Auswahl unter diesen Einträgen
> nichts beitragen — man kann aus nichts keine bessere Teilmenge ziehen."* Das ist ein
> **Kategoriefehler**. „Der Mittelwert des Pools ist nicht von null zu trennen" und „keine
> Teilmenge hat einen positiven Mittelwert" sind verschiedene Aussagen, und die zweite folgt
> nicht aus der ersten.
>
> An den eigenen Daten widerlegt (`python scripts/study_subset.py`): Pool **−0,0906 R**,
> Teilmenge `rating_band=eindeutig` **+0,0311 R** auf 588 Trades, Markt BTCUSDT **+0,0266 R**
> — beide Merkmale stehen vor dem Trade fest. Besonders unangenehm: das Projekt hatte drei
> Tage vorher **Setup C abgeschaltet**, weil seine Teilmenge schlechter war als der Rest. Der
> Satz widersprach einer Entscheidung, die auf genau dieser Grundlage getroffen wurde.
>
> Was weiterhin gilt: die Teilmenge ist **kein Fund**. Ihr Intervall umspannt die Null
> ([−0,093; +0,160]), und gegen einen Zufallsfilter gleicher Selektivität liegt sie nur knapp
> über dessen 97,5-%-Punkt. Daraus wurde **E1**, vorab registriert — und E1 ist gelaufen:
> über 42 849 Kandidaten aus 11 Märkten schlagen beide Modelle den Zufallsfilter und bleiben
> **absolut negativ** (logistisch −0,1052 R, LightGBM −0,0908 R). Eine Auswahl kann also
> besser als Zufall sein und trotzdem Geld verlieren. Siehe `audit/RECHERCHE_KORREKTUREN.md`
> §3.1.

### 6.5 Die Setups

**[FAKT]** Sechs regelbasierte Muster, fünf davon aktiv:

| Schlüssel | Name | Status |
|---|---|---|
| A | Momentum-Breakout | aktiv |
| B | Trendlinien-Fakeout | aktiv |
| C | Supply/Demand-Retest | **abgeschaltet am 04.10.2026** |
| E | Orderblock nach Noc Trading | aktiv |
| F | Inducement-Orderblock | aktiv |
| G | Sechs-Faktoren-FVG | aktiv |

(Es gibt kein D.)

**[GEMESSEN] Warum C abgeschaltet wurde** — ein Beispiel dafür, wie hier Entscheidungen
fallen. Über vier Märkte und vier Jahre: **mit C** läuft der Pool auf −0,0920 R und das
Intervall schliesst die Null aus; **ohne C** auf −0,0583 R bei einem Drittel weniger Trades,
Trefferquote 32 → 37 %, und das Intervall enthält zum ersten Mal die Null. **Mehr als die
Hälfte des Gesamtverlusts kam aus diesem einen Setup.** Rückgängig zu machen, indem C wieder
in `config/settings.yaml` → `setups.enabled` aufgenommen wird.

### 6.6 Daten auf Platte

**[GEMESSEN]** `python scripts/coverage.py`:

| Quelle | Abdeckung | Zeitraum |
|---|---|---|
| OHLCV (W1/D1/H4/H1/M15/M1) | **12/12 Märkte** | D1 gemeinsam ab 2021-10-15, teils ab 2020-01 |
| Funding | **12/12** (1 defekt, s. u.) | 3,8–6,7 Jahre, 8-Stunden-Raster, 0 Lücken |
| Open Interest | **4/12** (BTC, ETH, SOL, XRP) | 5,0 Jahre, 60-min-Raster, 0 Lücken |
| Account Ratio | **4/12** | 5,0 Jahre, 5 Lücken (9 Punkte) |
| Taker-Flow | **2/12** (BTC, ETH) | 6,9–7,1 Jahre, 0 Lücken |
| Coin Metrics (on-chain) | 9 Märkte, 13 Spalten | bis 11,8 Jahre |
| DefiLlama (Stablecoins) | 1 Serie, 6 Spalten | 8,8 Jahre |
| FRED (Makro) | 6 Serien, **ohne API-Schlüssel** | 10–65 Jahre |
| Sentiment | **0/12** | — |

Märkte: BTC, ETH, SOL, XRP, ADA, AVAX, LINK, DOGE, BNB, LTC, DOT, ATOM (alle USDT).

---

## 7. Was nachweislich gut läuft

Dies ist der Teil, auf den ich die Recherche ausdrücklich hinweisen möchte: **Die
Hauptleistung dieses Projekts ist nicht ein Handelssystem, sondern ein Apparat, der eigene
Scheinfunde fängt.**

### 7.1 Acht Scheinfunde, gefangen bevor sie geglaubt wurden

**[GEMESSEN]** Alle acht wurden intern entdeckt, vier davon in Code, den ich selbst Minuten
vorher geschrieben hatte:

1. **Tautologische Dezil-Tabelle** — sortierte nach einer Grösse und berichtete sie zurück.
2. **Überlappende Fenster** — Intervall mehrfach zu eng.
3. **Punktschätzung als Besetzungs-Behauptung** — ein Punktwert gegen ein Intervall auf
   einer *anderen* Grösse aus denselben 358 Zeilen.
4. **Imbalance-Buchhaltungsidentität** — „gefunden" war eine Umformung der Definition.
5. **Unpaarige Abstinenz-Vergleiche** — Mischung von Dauern/Märkten trug das Ergebnis.
6. **`atr_pct`-Zustandszelle** — scheiterte an Bonferroni *und* wiederholte sich nur zu
   0,16–0,26×.
7. **Crossover ohne Intervall** berichtet.
8. **Querschnitts-Momentum `mom_7`** (heute) — Intervall ohne Null, fällt aber an der
   Mehrfachkorrektur **und** wiederholt sich zu **0,04×**.

### 7.2 Die Schutzvorrichtungen, die das leisten

**[FAKT]**

| Mechanismus | Was er verhindert |
|---|---|
| **Zukunfts-Mutationstest** | Snapshot bauen, alle Bars *nach* Index *i* zufällig verändern, Snapshot erneut bauen — SHA-256 muss identisch sein. Fängt Repainting, falsches Resampling, globale Normalisierung und History-Leaks in einem Test. |
| **Purged + embargoed Walk-forward auf Zeitstempeln** | Alle Märkte eines Tages bleiben auf derselben Seite der Grenze. Ein Nachbar aus den letzten 48 h hat ein überlappendes Ergebnis und ist verbotenes Wissen. |
| **Wochenblock-Bootstrap über alle Märkte gemeinsam** | Zeilen-Resampling gäbe Intervalle, die mehrfach zu eng sind, weil 12 Märkte sich gemeinsam bewegen. |
| **Bonferroni auf die *angemeldete* Zellenzahl** | Zellen werden vor dem Lesen deklariert. |
| **Wiederholung in einem zweiten Fenster** | Zweites Tor. Band: Faktor 0,5–2,0. |
| **Unangetastetes Prüffenster** | **0 Konsultationen** über 124 Versuche. Jede Konsultation verschärft die geforderte Konfidenz für die nächste. |
| **Register mit Einheitenprüfung** | `Register.judge` lehnt jeden Arm ab, der nicht in R gemessen ist — ein Arm kann den Champion nur auf der Skala schlagen, auf der ein Trade beurteilt wird. |
| **Lauf-Signatur** | Enthält die Risikokonfiguration. Ändert man einen Deckel, verwaisen alle gespeicherten Signale — sichtbar statt still. |
| **Provenienz-Zustände** | `VERIFIED`, `CROSS_VENUE`, `MIXED`, `UNKNOWN`; nur `{VERIFIED, CROSS_VENUE}` sind nutzbar. |
| **`available_at <= decision_time`** | Pro Quelle deklarierte Veröffentlichungsverzögerung plus Maximalalter. |
| **Abdeckungsregister** | Zählt Zeilen, Lücken, Dubletten, exakte Nullen und Dezimalstellen-Signaturen pro Quelle. |

### 7.3 Weitere Dinge, die funktionieren

- **[FAKT]** Der Papierhändler überlebt Neustarts: Zustand pro Konto in SQLite, Fortsetzung
  nach **Zeitstempel** statt nach Zeilenposition, also wird keine Minute doppelt verbucht.
- **[FAKT]** `trade_id` ist deterministisch (`live-SYMBOL-timestamp`). Als versehentlich zwei
  Händler gleichzeitig liefen, hat der Speicher die Schreibvorgänge **zusammengeführt** statt
  doppelt zu zählen. Geprüft: 0 doppelte IDs, 0 wiederholte Markt+Zeit-Paare.
- **[FAKT]** `scripts/ft.py` erzwingt die vollständige Konfigurationskette und prüft den
  Rückgabewert selbst.
- **[FAKT]** Der Simulator rechnet Gebühren, Funding und Liquidation; `sim/` und
  `execution/` teilen sich einen Zustandsautomaten.
- **[FAKT]** `study_refused.py` speichert **abgelehnte** Signale mitsamt der Regel, die sie
  abgelehnt hat — so lässt sich fragen, ob eine Regel Geld kostet.
- **[GEMESSEN 07.10.2026]** Und die Frage ist jetzt beantwortet, über **zwölf Märkte und
  41 382 gelabelte Signale**. Alle drei Ablehnungsregeln sind bestätigt, jede auf ihrem
  eigenen Intervall:

  | Gruppe | n | brutto | netto | Treffer | Brutto-Intervall |
  |---|---|---|---|---|---|
  | genommen | 6 683 | +0,0080 | −0,0210 | 38 % | [−0,022, +0,039] — **spannt über Null** |
  | abgelehnt, alle | 34 699 | **−0,0309** | −0,1568 | 44 % | **[−0,045, −0,016]** |
  | abgelehnt, Kostenregel | 19 427 | −0,0379 | −0,1936 | 37 % | [−0,060, −0,017] |
  | abgelehnt, Chance:Risiko | 15 252 | −0,0219 | −0,1099 | **54 %** | [−0,038, −0,006] |
  | abgelehnt, Liquidation | 20 | −0,1614 | −0,1674 | 35 % | [−0,309, −0,032] |

  Drei von drei: jede abgelehnte Population ist **brutto** schlechter als nichts, und jedes
  Intervall schliesst die Null aus. Die Regeln lehnen nicht bloss teure Trades ab, sondern
  Trades, die Geld verlieren, **bevor** eine Gebühr anfällt. Keine dieser Regeln ist ein Hebel.

  Zwei Dinge dazu, die unangenehmer sind als die Bestätigung selbst. **Erstens** ist der
  Brutto-Vorteil der genommenen Population verschwunden: bei vier Märkten las er +0,0136, bei
  zwölf steht er bei +0,0080 mit einem Intervall, das über die Null spannt. Jede Erweiterung
  der Stichprobe hat ihn Richtung Null bewegt. **Zweitens** liegt die Trefferquote der
  abgelehnten Signale mit 44 % **über** der genommenen von 38 %, bei Chance:Risiko sogar bei
  54 % — und alle sind brutto negativ. Das ist die dritte unabhängige Messung derselben
  Sache: eine Population mit höherer Trefferquote verdient weniger.

  Und was es nicht ist: diese Signale haben nie um einen Platz konkurriert. Ein positiver
  Befund verdiente einen Backtest-Arm mit gelockerter Regel — niemals die Erlaubnis, eine
  Regel abzuschalten.

---

## 8. Das vollständige Forschungsregister — 17 Familien

**[GEMESSEN]** `python scripts/ratchet.py`: **16 erledigt, 0 offen, 1 nicht testbar.**
**Keine einzige Familie ist positiv.**

| # | Familie | Zustand | Ergebnis |
|---|---|---|---|
| 1 | Fortsetzung / Zonen-Rückkehr | erledigt | 9 Hypothesen, 8 tot, 1 unentschieden |
| 2 | Volatilitätsausbruch | erledigt | 42 Zustandszellen × 2 Horizonte, kein Treffer; der eine Kandidat scheitert an der Korrektur und wiederholt sich zu 0,16–0,26× |
| 3 | VWAP und Tageszeit | erledigt | 3 Sessions × 2 Horizonte, Differenz < 0,01 %, alle Intervalle mit Null |
| 4 | Mean Reversion | erledigt | Brutto 0,17 bp auf M15 über 700 000 Beobachtungen (reproduziert ein Preprint), **Maut 79×** |
| 5 | Handelsspannen-Ausbruch | erledigt | Donchian-Position in Terzilen: kein Band ohne Null |
| 6 | Momentum mit Volumen | erledigt | Bewegung × Relativvolumen: kein Band ohne Null |
| 7 | Trendfolge mit Rücksetzer | erledigt | **Umgekehrt widerlegt:** OHNE Rücksetzer ist am besten (+0,367 %), wiederholt sich aber nur zu 0,29× |
| 8 | Regime-Umschaltung | erledigt | Differenz der Differenzen: +0,257 % [−0,073, +0,609] auf 24 h; +0,007 % [−1,139, +1,121] auf 168 h |
| 9 | Funding / Relative Value (als *Merkmal*) | erledigt | Funding als Perzentil: kein Band ohne Null |
| 10 | Orderflow (Taker-Volumen) | erledigt | 30 Zellen, keine positiv |
| 11 | Orderflow (Orderbuch-Tiefe) | **nicht testbar** | Keine historischen Snapshots verfügbar |
| 12 | Längere Horizonte (Preis allein) | erledigt | 24/72/168 h × 2 Modelle × 3 Märkte: keine Konfiguration schlägt ihre Basisquote |
| 13 | Makro (FRED) | erledigt | 6 Serien, 10–65 Jahre. P vs. P+M auf **allen drei** Horizonten schlechter als Preis allein (+1,87→+1,21; −0,03→−0,44; −0,75→−1,02). Durchgehende Richtung = Signatur von Rauschen |
| 14 | On-Chain + Stablecoin-Liquidität | erledigt | 16 statt 7 Merkmale: kein Vorsprung; bei 72 h/LightGBM ein Intervall ohne Null in die **falsche** Richtung (−3,66) |
| 15 | Längere Horizonte (mit Derivaten) | erledigt | Herkunft nachgemessen (Bybit, exakt). Unterschied ±1,6 Punkte ohne Richtung |
| 16 | **Funding-Carry (ohne Richtung)** | erledigt | Siehe 8.1 |
| 17 | **Querschnitt (Markt gegen Markt)** | erledigt | Siehe 8.2 |

### 8.1 Funding-Carry — die einzige belegte Einnahme, und sie schrumpft

**[GEMESSEN]** `python scripts/study_funding_carry.py`. Perp short gegen Spot long, Preis
herausgehedgt, **keine Vorhersage nötig**.

> **Zwei Korrekturen vom 07.10.2026.** Erstens: BNBUSDT war hier mit der Begründung
> ausgeschlossen, 49,6 % exakte Nullen seien ein Datenloch. **Die Nullen sind echt** — an
> 200 identischen Zeitstempeln sind 73 von 73 auch bei der Venue null, und die Datei gibt
> die Börse zu 100,0 % wieder. Es war eine Plausibilitätsannahme, keine Messung.
>
> Zweitens, und schwerer: **das Funding-Verzeichnis mischt zwei Börsen.** An identischen
> Zeitstempeln gemessen (`python scripts/verify_funding_provenance.py`) sind vier Märkte
> Bybit (96–97 % identisch) und acht Binance (100,0 %). `learn/panel.py::SOURCES` führt
> `funding` seit je als „gemischte Börse" und `check_provenance` meldet es — **die
> Carry-Studie hat es nur nie abgefragt.** Eine Schutzvorrichtung, die existiert und nicht
> benutzt wird, ist keine.
>
> Folge für die Trendaussage unten: die Bybit-Reihen beginnen 2023, die Binance-Reihen 2020,
> also verglich „erste gegen zweite Hälfte" je Markt **verschiedene Kalenderfenster**. Auf
> dem gemeinsamen Fenster neu gerechnet fallen **11 von 12** (Bybit 4/4, Binance 7/8) — der
> Rückgang überlebt. Aber zwölf stark korrelierte Märkte sind **eine** gut belegte
> Beobachtung eines gemeinsamen Trends, nicht zwölf unabhängige.

11 Märkte (BNBUSDT vorher ausgeschlossen,
s. 9.1), 3,8–6,7 Jahre.

| Markt | je 8 h | 95 %-Intervall | positiv | p. a. aufs Notional | Amortisation |
|---|---|---|---|---|---|
| LTCUSDT | +0,0135 % | [+0,0112, +0,0160] | 82,1 % | **+14,78 %** | 3,7 T |
| LINKUSDT | +0,0125 % | [+0,0100, +0,0152] | 82,4 % | +13,73 % | 4,0 T |
| ADAUSDT | +0,0123 % | [+0,0099, +0,0149] | 80,2 % | +13,46 % | 4,1 T |
| DOGEUSDT | +0,0113 % | [+0,0088, +0,0139] | 82,3 % | +12,37 % | 4,4 T |
| ATOMUSDT | +0,0088 % | [+0,0057, +0,0119] | 65,6 % | +9,63 % | 5,7 T |
| XRPUSDT | +0,0077 % | [+0,0063, +0,0093] | 80,1 % | +8,44 % | 6,5 T |
| DOTUSDT | +0,0071 % | [+0,0042, +0,0101] | 66,3 % | +7,79 % | 7,0 T |
| BTCUSDT | +0,0068 % | [+0,0058, +0,0079] | 83,9 % | +7,41 % | 7,4 T |
| ETHUSDT | +0,0067 % | [+0,0057, +0,0079] | 82,0 % | +7,39 % | 7,4 T |
| AVAXUSDT | +0,0063 % | [+0,0034, +0,0092] | 71,4 % | +6,87 % | 8,0 T |
| SOLUSDT | +0,0050 % | [+0,0027, +0,0071] | 73,2 % | +5,47 % | 10,0 T |

**11 von 11 mit Intervall ganz über null.** Und dann die Prüfungen:

**[GEMESSEN] Wiederholung, erste vs. zweite Hälfte:**

| Markt | erste Hälfte | zweite Hälfte | Verhältnis |
|---|---|---|---|
| ADAUSDT | +0,0182 % | +0,0063 % | 0,35× |
| ATOMUSDT | +0,0198 % | **−0,0023 %** | −0,11× |
| AVAXUSDT | +0,0078 % | +0,0047 % | 0,60× |
| BTCUSDT | +0,0092 % | +0,0043 % | 0,47× |
| DOGEUSDT | +0,0152 % | +0,0074 % | 0,48× |
| DOTUSDT | +0,0111 % | +0,0031 % | 0,28× |
| ETHUSDT | +0,0089 % | +0,0045 % | 0,51× |
| LINKUSDT | +0,0174 % | +0,0077 % | 0,44× |
| LTCUSDT | +0,0193 % | +0,0076 % | 0,40× |
| SOLUSDT | +0,0078 % | +0,0022 % | 0,28× |
| XRPUSDT | +0,0115 % | +0,0039 % | 0,34× |

**11 von 11 zahlen in der zweiten Hälfte weniger.** Rauschen streut; das hier fällt überall.
Eine einheitliche Richtung über elf Märkte ist ein Trend.

**[GEMESSEN] Woher das Geld kommt:** Im Mittel **39 % aller Perioden liegen exakt auf dem
Standardsatz der Börse** (0,01 % je 8 h). Diese Einnahme ist überwiegend ein **Parameter,
den die Börse setzt**, keine Fehlbewertung, die jemand gefunden hat.

**[GEMESSEN] Hilft Auswählen?** Mit **perfekter Voraussicht jeder künftigen Rate**, in
zusammenhängenden Blöcken von 3/7/14/30 Tagen, jeder mit einer Mautzahlung:

> In **7 von 11** Märkten schlägt perfekte Auswahl nicht einmal das blosse Durchhalten.
> Grund: Auswahl zahlt die Maut jedes Mal, Durchhalten einmal.
> Beste Zelle überhaupt: +6,77 % p. a. aufs Notional → **12 000 CHF → 12 027 CHF** in 24 Tagen.
> **0,9 % der Lücke.**

**[OFFEN] Was die Messung nicht sehen kann — und es ist nicht klein:**

1. **Es gibt keine Spot-Reihe auf der Platte**, nur den Perp. Die Basis zwischen Einstieg und
   Ausstieg ist nicht gemessen, sondern weggelassen. **Jede Zahl oben ist eine Obergrenze,
   keine Schätzung.**
2. **Das Kapital ist doppelt gebunden**, solange die Börse die Beine nicht als Margin
   verrechnet. Rendite aufs Kapital = Hälfte der Rendite aufs Notional.
3. **Die eigentliche Todesursache steht in keiner Spalte:** Das Short-Bein braucht Margin.
   Steigt der Preis scharf, verliert der Perp, während der Gewinn im Spot-Bein auf einem
   anderen Konto liegt und nicht nachschiesst. Wird das Short-Bein liquidiert, bleibt ein
   ungehedgtes Long stehen — aus einem richtungslosen Trade wird eine volle Wette, und zwar
   genau dann, wenn das Funding am höchsten war.

### 8.2 Querschnitt — die letzte unbeobachtete Richtung des natürlichen Raums

**[FAKT] Warum diese Familie fehlte:** Alle 87 Arme davor massen einen Markt gegen seine
**eigene** Zukunft, mit „immer long" als Basis. Die zwölf Märkte bewegen sich gemeinsam. Ein
Modell, das gefragt wird „steigt Markt m?", wird im Wesentlichen zwölfmal gefragt „steigt
Krypto?" — und „immer long" besteht aus genau dieser gemeinsamen Bewegung. Die Suche hat ein
Modell gebeten, den gemeinsamen Faktor darin zu schlagen, der gemeinsame Faktor zu sein.

**[GEMESSEN]** `python scripts/study_cross_section.py`. Long oberstes Drittel, short
unterstes, gleichgewichtet, nicht überlappend, 12 Märkte, 2021-10-15 bis 2026-10-05
(1 817 Tage). Drei Rangfolgen × zwei Horizonte = **6 Zellen deklariert vor dem Lesen**,
Schwelle also 0,0083.

| Rangfolge | Horizont | Perioden | Umschlag | Spanne | 95 %-Intervall | netto | korrigiert |
|---|---|---|---|---|---|---|---|
| mom_30 | 1 T | 1 786 | 12,2 % | +0,0520 % | [−0,0444, +0,1515] | +0,0337 % | nein |
| mom_30 | 7 T | 255 | 25,9 % | +0,2236 % | [−0,4456, +0,9059] | +0,1848 % | nein |
| **mom_7** | **1 T** | 1 809 | 21,7 % | **+0,1036 %** | **[+0,0108, +0,1978]** ✱ | **+0,0710 %** | **nein** |
| mom_7 | 7 T | 258 | 32,9 % | +0,6243 % | [−0,0416, +1,2816] | +0,5750 % | nein |
| vol_30 | 1 T | 1 786 | 4,9 % | −0,0155 % | [−0,1235, +0,0899] | −0,0227 % | nein |
| vol_30 | 7 T | 255 | 16,0 % | −0,1142 % | [−0,8328, +0,5992] | −0,1382 % | nein |

Die eine Zelle mit Intervall ohne Null:

```
mom_7 / 1 T
  brutto +0.1036%, Maut 0.0326%, netto +0.0710%
  Mehrfachkorrektur (99.17%):  FÄLLT
  Wiederholung: erste Hälfte +0.1897%, zweite +0.0071%, Verhältnis 0.04x  FÄLLT
  -> nicht belegt
```

**[OFFEN] Verzerrung:** Alle zwölf Märkte existieren noch. Jeder in diesen fünf Jahren
verschwundene Markt fehlt samt seinen Fenstern, und sein Fehlen schmeichelt genau dem Arm,
der vergangene Gewinner kauft. Die Verzerrung zeigt **in Richtung eines positiven
Ergebnisses**.

### 8.3 Der Kostendeckel — die einzige Änderung mit einer sicheren Komponente

**[GEMESSEN]** `config/risk.yaml`, `max_cost_fraction_of_risk` von 0,15 auf **0,08** gesenkt.
Sweep über 3 300 gelabelte Trades auf 4 Märkten:

| Deckel | Trades | Anteil | R/Trade | R TOTAL |
|---|---|---|---|---|
| 0,15 | 1 652 | 99,3 % | −0,0120 | −19,7 |
| **0,08** | **786** | **47,2 %** | **+0,0360** | **+28,3** |
| 0,04 | 275 | 16,5 % | +0,1148 | +31,6 |

**[GEMESSEN] Zerlegung — was sicher ist und was nicht:**

| Komponente | Wert | Intervall | Status |
|---|---|---|---|
| Kosten | −0,0395 | [−0,041, −0,038] | **sicher, und arithmetisch** (Korrelation +0,83 mit dem Filter) |
| Brutto | +0,0799 | [−0,033, +0,195] | **nicht belegt** (Korrelation −0,004) |
| Netto | +0,1190 | [+0,005, +0,234] | — |

**Konservativ gelesen** (Brutto-Differenz null, was das Intervall erlaubt): Der Deckel bewegt
einen Trade von **−0,054 R auf −0,015 R**. Immer noch negativ, 3,6× weniger — rein daraus,
dass die Maut seltener bezahlt wird. **Es ist kein Vorteil und darf nicht als einer berichtet
werden.**

**[ENTSCHEIDUNG] Warum 0,08 und nicht 0,04**, das besser mass: 0,08 behält 94 % der
Verbesserung bei 2,9-fachem Trade-Fluss. Kriterium „Evidenz-Durchsatz", **vor** dem Lesen des
Sweeps genannt — das ist auch, was verhindert, dass der Parameter auf seine eigene beste
Zelle angepasst wird.

**[GEMESSEN] Nachgeprüft am 06.10.2026:** 2,27 Trades/Tag → ~60 Vorwärts-Trades bis zum
30.10., gegen die Vorhersage „etwa fünfzig". **Das Kriterium hielt.**

### 8.4 Die verbleibende Möglichkeit: die Wette, mit Basisrate

**[GEMESSEN]** `python scripts/study_goal_window.py`. Über alle 12 Märkte und **25 960
Fenster** von 24 Tagen:

| Markt | Fenster | ≥ +25 % | Median | schlechtestes | ≤ −20 % |
|---|---|---|---|---|---|
| LINKUSDT | 2 430 | **18,0 %** | +1,4 % | −58,3 % | 15,4 % |
| AVAXUSDT | 2 180 | 17,8 % | −1,9 % | −63,8 % | 20,4 % |
| ADAUSDT | 2 416 | 16,9 % | −1,7 % | −61,5 % | 15,4 % |
| SOLUSDT | 1 793 | 16,0 % | −1,1 % | −64,8 % | 16,5 % |
| ATOMUSDT | 2 409 | 15,1 % | −2,7 % | −66,5 % | 15,8 % |
| DOGEUSDT | 2 255 | 14,4 % | −2,1 % | −53,8 % | 15,1 % |
| DOTUSDT | 2 212 | 14,2 % | −4,6 % | −54,9 % | 18,0 % |
| LTCUSDT | 2 438 | 12,4 % | +0,3 % | −59,7 % | 10,7 % |
| ETHUSDT | 1 807 | 11,5 % | −1,0 % | −48,8 % | 9,8 % |
| XRPUSDT | 1 807 | 11,2 % | −2,4 % | −49,9 % | 8,2 % |
| BNBUSDT | 2 406 | 11,0 % | +2,0 % | −60,7 % | 7,0 % |
| **BTCUSDT** | 1 807 | **5,8 %** | +0,2 % | −38,1 % | 5,4 % |

```
Über alle:  13.9% der Fenster brachten +25% oder mehr  (etwa jedes 7.)
            8.0% verloren 25% oder mehr
            Verhältnis 1.74 zu 1
```

**[FAKT] Was daraus folgt, unbequem in beide Richtungen:** Das Ziel ist nicht unmöglich — es
ist historisch oft genug passiert. Es ist nur nichts, worauf ein *System* hinarbeiten kann.
Wer es will, kauft und hofft; die Trefferquote ist der ganze Plan, und die Verlustquote
gehört dazu. Die Wette müsste zudem auf einen **kleinen** Markt gehen (BTC 5,8 % vs. LINK
18,0 %), und das sind genau die mit den −60 %-Fenstern.

**[OFFEN] Verzerrung:** Alle zwölf Märkte existieren noch; verschwundene Märkte fehlen samt
ihrer Verlustfenster. **Die echte Trefferquote ist niedriger als die gezeigte, nicht höher.**

---

## 9. Alle bekannten Probleme, nach Schwere

### 9.1 Datenprobleme

| # | Problem | Status | Auswirkung |
|---|---|---|---|
| D1 | **BNBUSDT-Funding: 49,6 % der Abrechnungen exakt null**, über die ganze Historie verteilt (2020-02 bis 2026-10). Keine Börse rechnet so oft genau nichts ab. | **erkannt, vom Messskript ausgeschlossen** (Schwelle 10 % exakte Nullen) | Hätte als „Markt ohne Funding" berichtet werden können — eine Schlussfolgerung aus einem Loch. |
| D2 | LINKUSDT (4,7 %) und LTCUSDT (4,2 %) haben denselben Defekt, **beschränkt auf Jan–Aug 2020** | toleriert | Berührt die zweite Hälfte nicht, auf der das Urteil ruht. |
| D3 | **Open Interest und Account Ratio nur für 4 von 12 Märkten** | [OFFEN] | Derivate-Familie nur auf einem Drittel der Märkte prüfbar. |
| D4 | **Taker-Flow nur für 2 von 12** (BTC, ETH) | [OFFEN] | Orderflow-Familie schmal. |
| D5 | **Sentiment: 0 von 12** | [OFFEN] | Nie gemessen. |
| D6 | **Keine Spot-Preisreihe** — alles auf Platte ist der Perp | [OFFEN] | Basis-Risiko des Carry-Trades **unmessbar**. |
| D7 | **Keine historischen Orderbuch-Snapshots** | **nicht testbar** | Orderbuch-Tiefe und Market-Making-Ideen sind nicht validierbar. |
| D8 | **Keine Daten zu verschwundenen Märkten** | [OFFEN] | Survivorship-Bias in jeder markt­übergreifenden Zahl, Richtung bekannt (zu optimistisch). |
| D9 | `account_ratio`: 5 Lücken (9 fehlende Punkte) in 5 Jahren, 3 exakte Nullen in `buy_ratio` | geringfügig | — |
| D10 | Alle Derivate-Werte auf 4 Dezimalstellen — **Herkunftssignal, kein Beweis** | geprüft | Herkunft nachgemessen: Bybit, exakt bis zur letzten Stelle. Ein falscher Docstring hat diese Achse einen Tag lang blockiert. |

### 9.2 Methodische Probleme und Fallen

| # | Problem | Status |
|---|---|---|
| M1 | **Haltedauer korreliert mit dem Ergebnis (+0,519).** Jede Vergleichsgrösse auf realisierter Dauer erbt ihre Antwort. | gelöst: Horizont wird vorgegeben |
| M2 | **`pandas` 3 wählt die Zeiteinheit pro Datei.** `.astype("int64")` liefert die gespeicherte Einheit. Falsche Division → leere Scheibe → Basis exakt null → Vorsprung sieht echt aus. | gelöst: `.dt.as_unit("ms")` + Verweigerung leerer Fenster |
| M3 | **`champion_mean_r` steht in *jeder* Registerzeile**, auch bei Einheiten wie Rangkorrelation. Eine naive Abfrage `low > champion_mean_r` meldet 37 „Gewinner", die Einheitenverwechslungen sind. | `Register.judge` prüft `unit != "R"` zuerst; `decide()` dokumentiert die Falle |
| M4 | **Zero-Breite-Intervalle** (`[0,0000, 0,0000]`) im Register, z. B. `zeitausstieg_24h`. Null Breite ist kein enges Intervall, sondern gar keins. | erkannt, explizit ausgeschlossen und benannt |
| M5 | **Barrier- und Vorzeichen-Labels stimmen auf 29–33 % derselben Kerzen nicht überein.** Richtungstrefferquote und Trade-Winrate dürfen nie gemischt werden. | dokumentiert in `audit/ZIELRECHNUNG.md` |
| M6 | **`status-time` einer externen Quelle ist eine Revalidierungszeit, keine Verfügbarkeit.** Hätte jedes Vor-2026-Merkmal als unverfügbar markiert und still jedes Modell geleert. | gelöst: konservative Konstante je Quelle |
| M7 | **Eine Konfigurationsänderung verwaist alle gespeicherten Signale.** Hat vier Studien „keine Signale" melden lassen, während 12 843 in der Datei lagen. | gelöst: `SignalStore.resolve()` + `--any` |
| M8 | **Ein Test, der nachrechnet, was er prüft, beweist nichts.** Ein Test behauptete eine handgerechnete Epoche, die zwei Tage falsch war; der Code war richtig. | Literal korrigiert, Lehre notiert |

### 9.3 Infrastruktur- und Werkzeugprobleme

| # | Problem | Status |
|---|---|---|
| I1 | **`pkill -f` aus Git Bash erreicht keine Windows-Prozesse.** Jeder „Neustart" fügte still einen weiteren Händler hinzu statt ihn zu ersetzen. | gelöst: `Get-CimInstance Win32_Process … \| Stop-Process -Force` |
| I2 | **Prozessketten zählen, nicht Zeilen.** Der venv-Launcher erzeugt ein Kindprozess, also erscheint jeder logische Prozess doppelt. Zählung über `ParentProcessId`. | dokumentiert |
| I3 | **`\| tail` verdeckt den Rückgabewert.** Eine fehlgeschlagene Datenlieferung meldete „exit code 0", weil der Code zu `tail` gehörte. Ist in dieser Session erneut passiert. | Regel: `{ cmd; echo "EXIT=$?"; } \| tail` oder in Datei umleiten |
| I4 | **Bash-Heredocs zerstören Backslash-Sequenzen** in Python-Strings in dieser Umgebung. `"\\n"` kommt als echter Zeilenumbruch an. Mindestens sechsmal passiert. | Regel: `Write`/`Edit` statt Heredoc, sobald Escapes im Inhalt sind |
| I5 | **FreqAI stürzt mit `STATUS_HEAP_CORRUPTION`** mitten in einem Walk-forward-Sweep bei Standard-Threadzahl. | Umgehung: `OMP_NUM_THREADS=2`. **Ursache unbekannt** [OFFEN] |
| I6 | **Freqtrade-Konfigurationskette:** Das Weglassen *einer* `-c`-Datei lässt das Schema einen leeren `jwt_secret_key` ablehnen und bricht ab, **bevor** eine einzige Kerze geladen wird. | gelöst: `scripts/ft.py` erzwingt die Kette |
| I7 | **Eine Überlagerung, die nicht zuletzt in der Kette steht, wird still von der Basis überschrieben** — und das sieht genauso aus, als würde sie gar nicht gelesen. | gelöst und dokumentiert |
| I8 | **Der Backtest endete am Geld, nicht am Fenster.** 1 000 → 201,93 USDT nach 15 Wochen; die restlichen 16 Monate waren Stille. Mein eigener Bericht sagte „2 425 Trades über 19 Monate". | gelöst: `config.measure.json` + aus den Daten abgeleiteter Berichtstext |
| I9 | **Zu grob formuliert, am 07.10.2026 an der installierten Version geprüft** (`freqtrade/.venv/Scripts/python scripts/ft_label_boundary.py`). Es sind **zwei** Grenzen: Training → Vorhersage ist **sauber**, weil ein überhängendes Label NaN ist und `filter_features` es verwirft — der Shift schützt sich selbst. Training → **interne Validierung** leckt: `make_train_test_datasets` ruft `sklearn.train_test_split` mit `shuffle=False`, also chronologisch geordnet und **ohne Abstand**, und genau diese Menge geht als `eval_set` an LightGBM. `buffer_train_data_candles` behebt das nicht und soll es nicht: es schneidet den Rand des Trainings-**Zeitfensters**. | **behoben:** `test_size` steht auf 0, damit `eval_set` entfällt und die Auswahl in den äusseren Walk-forward gehört. Alte Läufe mit `test_size > 0` bleiben als eingeschränkt markiert — ein Parameter von heute gibt keinen Lauf von gestern frei. |

### 9.4 Offene Punkte im System selbst

| # | Punkt | Status |
|---|---|---|
| S1 | **`calibration_proven: false`** — die Confidence-Stufen über 1 % Risiko sind gesperrt. Bis 05.10.2026 war das kein Beschluss, sondern ein Rechenunfall: Der Deckel verglich die Nachbarn **einer** Kerze (höchstens 120) mit einer Schwelle von 200, konnte also nie aufgehen. Richtig gedeckelt, falscher Grund. | **beantwortet 07.10.2026** (`scripts/study_calibration.py`). Die Frage brauchte `history.Case` gar nicht: das Journal speichert die Bewertung im `reason`-Block, also **vor** dem Ergebnis. Ergebnis in zwei Teilen. **Erstens**, die rohe Zahl `rating/100` ist keine Wahrscheinlichkeit, sondern stark überzuversichtlich — im Band 0,90–1,00 sagt sie 0,946 und beobachtet 0,373, auf 166 Fällen (Brier roh 0,3789). **Zweitens**, nach einer nur auf dem früheren Fenster angepassten Sigmoide ist sie von der Basisquote **nicht zu trennen**: gepaart −0,00005 mit [−0,00011, +0,00001], Null enthalten (Brier kalibriert 0,2246 gegen Basisquote 0,2247). `calibration_proven` bleibt `false` — aber nicht mehr aus Datenmangel, sondern weil in der Zahl, die den Schalter öffnen würde, **nichts steckt**. Das ist die härtere Aussage: mehr Fälle ändern sie nicht. |
| S2 | **Prüffenster: 0 Konsultationen.** Nicht eine Lücke, sondern eine Entscheidung — es ohne würdigen Kandidaten aufzubrauchen, verschiesst die einzige Munition. | bewusst |
| S3 | **Vorwärts-Evidenz: 10 Trades im Journal**, 02.10. bis 07.10., Mittel +0,333 R bei 50 % Treffern. Die Zahl steht hier nur, weil sie sonst jemand anders findet und für ein Ergebnis hält: **n = 10 ist kein Ergebnis**, und ein positives Mittel auf zehn Fällen ist genau die Form, in der dieses Projekt zehn Scheinfunde angefangen hat. Die Zuflussrate ist das eigentliche Problem — bei ~1,9/Tag brauchen 100 Vorwärts-Trades rund 52 Tage. | strukturell [OFFEN] |
| S4 | **Der FreqAI-Vergleich: Basislinie steht, Modellarm läuft** (`audit/FREQAI_VERGLEICH.md`). Der alte Vergleich verglich nichts — drei getrennte Defekte, alle behoben. Der Basislauf endete am **Geld**, nicht am Fenster: 1 000 USDT, nach 15 Wochen bei 201,93, danach 16 Monate ohne einen Trade, gemeldet als 2 425 Trades über 19 Monate. Mit Kapital, das nie bindet, macht dieselbe Strategie **15 624 Trades** — das Sechsfache. Der FreqAI-Arm lief 45 Tage gegen 579. Und `identifier` ist ein Cache-Schlüssel ohne die Konfiguration darin: der Lauf brach bei 75/83 ab und hatte vorher **74 Folds lang fremde Modelle stillschweigend wiederverwendet**. | Basislinie **erledigt**: −0,58 %, 526 Verlusttage von 579, Profit-Faktor 0,35, p-Wert 0. Modellarm **erledigt**: 921 Trades, −0,04 %, p-Wert 4,1e−06. **NICHT BELEGT** — und je Trade **25,8 % schlechter** als die Basislinie (−0,4659 gegen −0,3703 USDT). Der Filter senkt den Gesamtverlust um 92,6 %, indem er 94,1 % weniger handelt; er erzeugt keinen Vorteil, er hört auf, für dessen Abwesenheit zu zahlen. Trefferquote 54,7 % bei zuverlässigem Verlust. |
| S6 | **Eine Revision war nicht zu bemerken.** Der Zukunfts-Mutationstest deckt Preise ab, die *nach* der Entscheidung liegen. Er kann nicht decken, was diese Dienste wirklich tun: Geschichte **neu schreiben**. Coin Metrics revidiert `flash`-Zeilen, FREDs DTWEXBGS ist berechnet, und `ExternalStore.write` legt die revidierte Zeile über ihre Vorgängerin. Gleicher Code, gleiche Konfiguration, gleicher Zeitraum, zwei Monate auseinander — zwei verschiedene Panels, und nichts sah falsch aus. `Panel` trug die **Art** der Quelle, nie ihren **Inhalt**. | **behoben 07.10.2026**: `Panel.vintages` und `vintage_id`, je Quelle ein Fingerabdruck. Was `run_signature` für die Konfiguration ist, ist das für die Daten. `tests/test_vintage.py` trennt die drei Fälle mit drei verschiedenen Antworten — die Revision *vor* dem Schnitt ändert das Merkmal und ist **nicht** wegzusichern; zusicherbar ist nur, dass die zwei Läufe nie verwechselt werden. |
| S7 | **Dieses Orderbuch kann keinen Fill belegen** — so stand es hier, und es war richtig, solange nur das Buch da war. `study_venue_fills.py` musste 33 von 41 Verkleinerungen verwerfen (Preise, die der Markt nie erreicht hat) und die restlichen 8 als Kandidaten führen. | **aufgehoben 07.10.2026.** `recentTrades` trägt `ask_id` und `bid_id`, die Kennungen **beider** Seiten. Eine im Buch beobachtete Order, die in einem Trade auftaucht, **ist gehandelt worden** — das ist kein Indiz, das ist die Kennung. Gemessen auf BTC über 32 Minuten (`scripts/study_tape_fills.py`): von 11 023 beobachteten Orders **8,1 % belegt gefüllt, 90,2 % belegt storniert** (weg und in keinem Trade), 1,7 % liegen noch. Dazu die ersten echten Markouts — bedingt auf den Fill, Vorzeichen aus `is_maker_ask`, gegen ein aus dem Tape geschätztes Mid: −0,167 bp bei 1 s bis −1,057 bp bei 5 min, alle vier Intervalle ohne Null. **Negativ heisst zugunsten des Makers**, also das Gegenteil adverser Selektion — und 32 Minuten eines Marktes sind keine Lesung. Die 11-Stunden-Aufnahme läuft. Die 90,2 % sind eine Obergrenze: eine Lücke im Tape macht aus einem Fill eine scheinbare Storno, gemessen 13 Lücken auf ~425 Abfragen (~3 %). |
| S8 | **E4s Survivorship-Blocker ist aufgehoben.** Das Datenmanifest führte `point_in_time_universe` als Priorität 1 und E4 als blockiert. Zwei öffentliche, rein lesende Quellen genügen: `onboardDate` aus `exchangeInfo` für das Listing, und das Archiv `data.binance.vision`, das Verzeichnisse für Symbole listet, die `exchangeInfo` **nicht mehr kennt** — 1 061 gegen 924. | **gebaut** (`scripts/build_universe.py`, `data/universe/binance_um_perps.json`, in git). **31 echte Perp-Delistings von 906 USDT-Perps = 3,4 %**, alle 31 mit letztem Archivtag. Die erste Rechnung las 8,1 % — darin waren 52 datierte Lieferfutures (`BTCUSDT_210326`) mitgezählt, die nicht delistet, sondern **abgelaufen** sind. Faktor 2,4. Offen bleibt: `last_data` ist der letzte Tag *mit Daten*, also eine Untergrenze und kein Delisting-Datum; und `onboardDate` ist für jedes delistete Symbol verloren. **E4 selbst ist nicht gerechnet.** |
| S5 | **Sammlung abgeschlossen: 12 von 12 Märkten, 43 727 Signale.** Die offene empirische Frage ist beantwortet: die Brutto-Differenz zwischen billigen und teuren Trades ist **echt** — +0,0561 R mit [+0,017, +0,097], Null ausgeschlossen. Auf vier Märkten hatte sie noch [−0,033, +0,195] gespannt. Billige Trades **fangen mehr Bewegung**, sie zahlen nicht nur weniger Zoll. | **erledigt**; und weiterhin kein Edge: R pro Trade +0,0107 mit [−0,041, +0,061] spannt über Null |

---

## 10. Was ich bräuchte, um besser zu werden

**[FAKT]** Konkret, nach Hebelwirkung geordnet.

### 10.1 Daten, die heute fehlen und die Messungen freischalten würden

1. **Spot-Preisreihen** für dieselben 12 Märkte, gleicher Zeitraum.
   → Macht das **Basis-Risiko des Funding-Carry messbar**, heute die grösste unbekannte
   Grösse in der einzigen positiven Messung des Projekts.
2. **Historische Orderbuch-Snapshots** (Tiefe, mindestens L2, mindestens stündlich).
   → Schaltet die einzige als „nicht testbar" markierte Familie frei und wäre Voraussetzung
   für jede Market-Making-Idee.
3. **Open Interest und Account Ratio für die übrigen 8 Märkte.**
4. **Taker-Flow für die übrigen 10 Märkte.**
5. **Daten zu delisteten/verschwundenen Märkten** → behebt den Survivorship-Bias, dessen
   Richtung heute bekannt, aber dessen Grösse unbekannt ist.
6. **Funding-Raten mehrerer Börsen** → erlaubt Cross-Venue-Vergleiche; heute liegt nur eine
   Venue vor.

### 10.2 Methodische Verstärkung

7. **Eine Quelle für realistische Ausführungsannahmen**: Wie weit weicht ein Limit-Maker-Fill
   in diesen Märkten vom Signalpreis ab, und wie oft füllt er gar nicht? Heute wird
   maker/taker als Konstante angenommen.
8. **Confidence bei jedem aufgelösten Fall speichern** (`history.Case`), damit S1 beantwortbar
   wird.

### 10.3 Rechenressourcen

9. Die Sammlung über 12 Märkte braucht ~13 CPU-Minuten pro Markt bei zwei Threads.
   Mehr parallelisierbare Rechenzeit verkürzt den Zyklus zwischen Fragen und Antworten
   direkt — das ist heute der limitierende Faktor für die Zahl der prüfbaren Hypothesen.

---

## 11. Fragen für die Recherche — das Herzstück

**An die Recherche:** Dies sind die Stellen, an denen externes Wissen den grössten Unterschied
macht. Für jede Frage steht dabei, was das Projekt schon weiss, damit die Antwort nicht
wiederholt, was hier gemessen wurde.

### 11.1 Zur Maut — der härtesten Grenze

> **F1.** Welche real erreichbaren Gebührenstrukturen gibt es für einen Kleinanleger auf
> Krypto-Perpetuals (Maker-Rebates, VIP-Stufen, Token-Rabatte, Fee-Sharing,
> Market-Maker-Programme)? Was ist die **tatsächlich niedrigste** Round-Trip-Maut, die
> jemand ohne institutionellen Status erreicht?
> *Was wir wissen:* Die Spezifikation des Projekts nimmt maker 0,02 % / taker 0,055 % an.
> Der physikalische Boden (maker/maker) wäre 0,04 %. Der gemessene Einstiegsvorsprung ist
> 0,0106 % — **Faktor 3,8 zu wenig**. Eine Antwort ändert nur dann etwas, wenn sie unter
> 0,0106 % kommt.

> **F2.** Gibt es Venues oder Instrumente, bei denen die Round-Trip-Maut **strukturell**
> um mehr als eine Grössenordnung niedriger ist (z. B. Dezentrale Börsen mit
> Rebate-Modellen, Perp-DEXe, Intent-basierte Systeme)? Mit welchen Gegenkosten?

> **F3.** Wie verhält sich adverse Selektion bei passiven Limit-Orders in diesen Märkten?
> Ein Maker-Fill passiert bevorzugt, wenn der Preis gegen einen läuft. Gibt es gemessene
> Zahlen zu diesem Effekt, und frisst er den Maker-Rabatt auf?

### 11.2 Zum Funding-Carry — der einzigen belegten Einnahme

> **F4.** Wie gross ist das **Basis-Risiko** eines Spot-Perp-Hedges in diesen Märkten
> empirisch? Welche Spannen nimmt die Basis an, wie schnell konvergiert sie, und was
> passiert in Stressphasen?
> *Was wir wissen:* Ohne Spot-Reihe ist das hier **nicht messbar**. Alle unsere Zahlen sind
> deshalb Obergrenzen.

> **F5.** Gibt es belastbare Daten zur Entwicklung der Funding-Raten über die letzten
> Jahre? Wir messen in **11 von 11 Märkten** einen Rückgang in der zweiten Hälfte der
> Historie. Ist das ein bekannter, dokumentierter Trend (Crowding des Basis-Trades,
> Zinsumfeld, ETF-Arbitrage) — und was sagt er über die kommenden Jahre?

> **F6.** Wie werden Spot- und Perp-Bein auf realen Börsen margin-technisch verrechnet
> (Portfolio Margin, Cross-Margin über Produkttypen)? Unsere Rechnung halbiert die Rendite,
> weil wir doppelte Kapitalbindung annehmen. Welche Venues tun das nicht?

> **F7.** Welche dokumentierten Fälle gibt es, in denen ein Basis-Trade über eine
> Liquidation des Short-Beins zu einem ungehedgten Long wurde? Welche Margin-Puffer werden
> dafür in der Praxis empfohlen?

### 11.3 Zu Ertragsquellen ausserhalb der Richtungsvorhersage

> **F8.** Welche **nicht-direktionalen** Ertragsquellen sind für einen Teilnehmer dieser
> Grössenordnung real zugänglich? Wir haben Funding-Carry gemessen. Was gibt es sonst, mit
> welcher gemessenen Grössenordnung und welchem Risiko?
> *Ausgeschlossen bei uns:* Market Making (keine Orderbuchdaten), Cross-Venue-Arbitrage
> (nur eine Venue, keine Ausführungsgeschwindigkeit).

> **F9.** Gibt es replizierte, veröffentlichte Belege für **nach Kosten** positive
> Krypto-Strategien bei Haltedauern von Stunden bis Wochen? Wir suchen nicht nach
> Backtest-Behauptungen, sondern nach Arbeiten mit Out-of-Sample-Prüfung,
> Mehrfachkorrektur und expliziten Transaktionskosten.
> *Was wir wissen:* 16 Familien, 124 Versuche, keine positiv. Mean Reversion auf M15
> reproduziert ein Preprint mit 0,17 bp Brutto — und 79-facher Maut.

> **F10.** Welche Faktormodelle für Krypto-Querschnitte (Momentum, Size, Volatilität,
> Liquidität, Illiquidität) halten einer Replikation stand, und mit welchen
> Transaktionskostenannahmen?
> *Was wir wissen:* Unser Querschnittsarm `mom_7/1T` zeigt +0,1036 % brutto, fällt aber an
> Korrektur und Wiederholung (0,04×).

### 11.4 Zur Methodik

> **F11.** Wie geht man mit **Survivorship-Bias in Krypto-Querschnitten** um, wenn
> historische Daten delisteter Märkte nicht frei verfügbar sind? Gibt es Quellen oder
> Korrekturverfahren?

> **F12.** Welche Verfahren eignen sich bei **wenigen Blöcken** (wir hatten einmal nur 16
> Wochenblöcke) besser als ein Perzentil-Bootstrap, der dort bekanntermassen zu eng läuft?
> (Stationärer Bootstrap, BCa, Block-Length-Wahl nach Politis–White?)

> **F13.** Wie wird in der Literatur die **Zahl der ausprobierten Konfigurationen** korrekt
> verrechnet, wenn Experimente adaptiv entstehen und nicht vorab vollständig deklariert
> werden können? (Deflated Sharpe Ratio, SPA-Test, Romano–Wolf?)

> **F14.** Wie verhindert man Label-Leakage bei Panel-Daten mit überlappenden Horizonten
> jenseits von Purging und Embargo? Gibt es anerkannte Prüfverfahren, die wir ergänzen
> sollten?

### 11.5 Zum Ziel

> **F15.** Gibt es eine seriöse, nicht-spekulative Methode, aus 12 000 CHF in 24 Tagen
> 15 000 zu machen, **ohne** eine Richtungswette?
> *Was wir wissen:* Unsere Messung sagt nein. Die einzige belegte Einnahme schliesst 0,9 %
> der Lücke, selbst bei perfekter Voraussicht. Die Basisrate der Wette ist 13,9 % pro
> 24-Tage-Fenster bei 8,0 % Gegenwahrscheinlichkeit für −25 %.
> **Eine ehrliche Antwort „nein" ist hier wertvoller als eine kreative.**

### 11.6 Zur Architektur des Kapitals

> **F18.** Zwölf getrennte Konten à 1 000 CHF oder ein Konto über 12 000? Heute riskiert
> jeder Trade 1 % **eines** Kontos (10 CHF = 0,083 % des Ganzen), und nie stehen mehr als
> 0,17 % des Gesamtkapitals gleichzeitig im Risiko.
> *Argument für die Trennung:* Zwölf Märkte sind stark korreliert; ein gemeinsames Konto mit
> 1 % je Trade und zwei offenen Positionen hätte bei einem gemeinsamen Markteinbruch die
> volle Korrelation im Portfolio.
> *Argument dagegen:* Die Zielrechnung wird dadurch um Faktor 12 härter, ohne dass das
> Risiko *pro Markt* steigt.
> **Gesucht:** Wie wird Positionsgrösse bei stark korrelierten Instrumenten in der Praxis
> und in der Literatur bestimmt (Risk Parity über korrelierte Assets, Portfolio-Heat,
> Kelly unter Korrelation)? Gibt es eine Formel, die beide Seiten korrekt abwägt, statt
> einer der beiden Intuitionen zu folgen?

> **F19.** Wie bestimmt man bei stark korrelierten Märkten die **effektive Stichprobengrösse**?
> Wir resampeln Wochenblöcke über alle Märkte gemeinsam, was die Intervalle korrekt
> verbreitert — aber wir haben keine Zahl dafür, wie viele *unabhängige* Beobachtungen in
> 2 742 Trades über 12 Märkte stecken. Ohne die Zahl ist jede Aussage „n ist gross genug"
> unbegründet.

### 11.7 Zur Infrastruktur

> **F16.** `STATUS_HEAP_CORRUPTION` in FreqAI/LightGBM unter Python 3.14 auf Windows bei
> mehreren Threads. Bekanntes Problem? OpenMP-Konflikt zwischen LightGBM und einer anderen
> Bibliothek im selben Prozess? **Umgehung ist `OMP_NUM_THREADS=2`, Ursache unbekannt.**

> **F17.** FreqAI bietet **kein Purging und kein Embargo**, und `shift(-label_period_candles)`
> lässt jede Foldgrenze überlappen. Gibt es eine saubere Erweiterung, einen Fork oder ein
> dokumentiertes Vorgehen dafür?

---

### 11.8 Welche Form einer Antwort hier etwas ändert

**[FAKT]** Damit die Recherche nicht in Material mündet, das nichts entscheidet:

**Brauchbar ist:**
- Eine **Zahl mit Quelle und Zeitraum**, die eine der Grössen oben ersetzt oder widerlegt
  (z. B. „die tatsächlich erreichbare Maut ist X %, Quelle, Stand").
- Ein **benannter Datensatz** mit Zugangsweg, Lizenz und Kosten — besonders für die sechs
  Lücken aus 10.1.
- Eine **replizierte Arbeit** mit Out-of-Sample-Prüfung, Mehrfachkorrektur und expliziten
  Transaktionskosten. Ein Backtest-Ergebnis ohne diese drei Dinge ist für uns kein Beleg,
  weil wir genau solche Ergebnisse achtmal selbst produziert und wieder verworfen haben.
- Ein **benannter Mechanismus**, warum eine Grösse so ist, wie sie ist (z. B. warum Funding
  in elf Märkten gleichzeitig fällt). Ein Mechanismus erlaubt eine Vorhersage; eine
  Korrelation nicht.
- Ein klares **„das geht nicht, und zwar deshalb"**. Das ist hier ausdrücklich ein
  wertvolles Ergebnis und kein Scheitern der Recherche.

**Unbrauchbar ist:**
- Eine Strategie-Idee ohne Kostenrechnung. Die Maut entscheidet hier alles.
- Ein Hinweis auf Parameteroptimierung. 124 Versuche; das Problem ist nicht die Suche.
- „Nimm mehr Hebel / engere Stops / grössere Positionen." Arithmetisch widerlegt (3.1).
- Ein Backtest-Screenshot oder eine Equity-Kurve ohne Methodenbeschreibung.
- Etwas, das die Randbedingungen aus Abschnitt 2 verletzt (Alter, Selbstausführung,
  Auszahlungsrechte).

### 11.9 Verwandte Auftragsdokumente

**[FAKT]** Es existieren fünf weitere Dokumente des Nutzers, die den Auftrag beschreiben und
für den Kontext nützlich sein können:
`TRADING_BRAIN_CLAUDE_INSTALLATION_PROMPT.md`, `TRADING_BRAIN_LOESUNGEN_UND_CLAUDE_AUFTRAG.md`
(Phasen A–F), `TRADING_BRAIN_ANALYSEN_UND_TESTPLAN.md`, `TRADING_BRAIN_CLAUDE_MASTERPROMPT.md`,
`TRADING_BRAIN_SELBSTLERNEND_MASTERPLAN_FUER_CLAUDE.md`,
`TRADING_BRAIN_KI_RECHERCHE_FUER_CLAUDE.md`.

---

## 12. Methodische Regeln, die ein Vorschlag respektieren muss

**[FAKT]** Diese Regeln haben hier acht Scheinfunde gefangen. Ein Vorschlag, der sie umgeht,
ist für dieses Projekt unbrauchbar.

1. **Nie gegen null vergleichen, wenn es eine Basisrate gibt.** „Immer long" ist die
   Basisrate, nicht 0,5.
2. **Nie eine Punktschätzung gegen ein Intervall halten**, und nie zwei Grössen aus denselben
   Zeilen vergleichen, als wären sie unabhängig.
3. **Zellen vor dem Lesen deklarieren** und die Schwelle auf die deklarierte Zahl korrigieren.
4. **Jede überlebende Zelle muss sich in einem zweiten Fenster wiederholen** (Band 0,5–2,0×).
5. **Wochenblock-Bootstrap über alle Märkte gemeinsam**, nie Zeilen-Resampling.
6. **Purged und embargoed auf Zeitstempeln**, nicht auf Zeilen.
7. **Niemals auf eine Grösse bedingen, die das Ergebnis mitbestimmt** (siehe die Haltedauer,
   +0,519).
8. **Eine Prozentzahl ohne ihr Auszahlungsschema ist kein Ergebnis.**
9. **Richtungstrefferquote und Trade-Winrate nie mischen** (29–33 % Uneinigkeit).
10. **Vorwärts- und Replay-Evidenz nie mitteln.**
11. **Das Prüffenster ist Munition, kein Werkzeug.** Jede Konsultation verschärft die Schwelle
    für die nächste.
12. **Ein Hebel, der nur die Trade-Anzahl ändert, kann das Vorzeichen nicht ändern.**
13. **Negative Befunde sind Ergebnisse.** Sie werden registriert, nicht versteckt.

---

## 13. Ausdrücklich als Vermutung gekennzeichnet

**[VERMUTUNG]** Alles in diesem Abschnitt ist **nicht gemessen**. Es steht hier, weil die
Recherche prüfen soll, ob etwas davon trägt — nicht, weil ich es glaube.

| # | Vermutung | Warum sie plausibel wirkt | Warum sie unbelegt ist |
|---|---|---|---|
| V1 | Der Rückgang der Funding-Raten in allen 11 Märkten ist ein Crowding-Effekt des Basis-Trades. | Einheitliche Richtung über 11 Märkte; der Trade ist bekannt und wird institutionell gefahren. | Wir haben keine Daten zu Positionierung oder Kapitalflüssen im Basis-Trade. Alternative Erklärungen (Zinsumfeld, ETF-Arbitrage, Regimewechsel) sind nicht ausgeschlossen. |
| V2 | Der 5-Minuten-Vorsprung von +0,0070 % ist Mikrostruktur-Fortsetzung (Fortschreiben der Bewegung, die das Signal ausgelöst hat), nicht Prognose. | Er existiert nur am kürzesten Horizont und verschwindet danach. | Nie getrennt gemessen. |
| V3 | Ein Teil der 86 % Ablehnungsquote der Risikoschicht ist zu streng, weil der Kostendeckel bei hoher Volatilität systematisch mehr ablehnt. | Die Ablehnungen verteilen sich sehr ungleich über die Märkte (ADAUSDT: 0 Vorschläge auf 110 Kerzen). | Die laufende Sammlung soll genau das beantworten; heute ist es eine Vermutung. |
| V4 | Mehr Märkte würden den Vorwärts-Durchsatz linear erhöhen, ohne eine Regel zu lockern. | Der Takt ist pro Markt etwa konstant. | Mehr Märkte heissen mehr korrelierte Beobachtungen — n wächst schneller als Information. Nicht gemessen, wie viel davon echte Evidenz ist. |
| V5 | Längere Haltedauern (Wochen statt Stunden) könnten die Maut besser amortisieren. | Die Maut ist pro Trade fix, die Bewegung wächst mit der Zeit. | Familie 12 und 15 haben längere Horizonte gemessen und nichts gefunden — allerdings als *Richtungsvorhersage*, nicht als Maut-pro-Bewegung. Die Unterscheidung ist offen. |
| V6 | Es gibt eine Ertragsquelle ausserhalb des gemessenen Raums. | 16 Familien sind der *angemeldete* Raum, nicht die Welt. | Reine Hoffnung, bis jemand eine benennt. |

**[VERMUTUNG]** Ebenfalls unbelegt: dass das Ziel von 15 000 CHF bis zum 30.10.2026 mit
irgendeiner Systemänderung erreichbar wäre. Die Messung sagt nein, aber eine Messung schliesst
nur den gemessenen Raum aus.

---

## 14. Reproduktionsbefehle

**[FAKT]** Alles folgende läuft auf dem vorhandenen Stand.

```bash
# Der Zustand des Ziels, mit der gemessenen Auszahlung
python scripts/goal.py

# Das vollständige Register, der Suchraum und die Entscheidung
python scripts/ratchet.py

# Abdeckung und Herkunft aller Datenquellen
python scripts/coverage.py

# Der zentrale Befund: Vorsprung des Einstiegs gegen die Maut
python scripts/ft.py --measure backtesting --strategy BaselineTrend --timerange 20250301-20261001
python scripts/study_freqtrade_gross.py

# Funding einsammeln, ohne eine Richtung zu behaupten
python scripts/study_funding_carry.py

# Querschnitt: ein Markt gegen die anderen
python scripts/study_cross_section.py

# Die Basisrate der verbleibenden Wette
python scripts/study_goal_window.py

# Papierhandel
python scripts/papertrade.py --status
python scripts/papertrade.py

# Die laufende Sammlung (beantwortet die offene Frage zum Kostendeckel)
python scripts/study_refused.py --symbols SOLUSDT,XRPUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOGEUSDT,BNBUSDT,LTCUSDT,DOTUSDT,ATOMUSDT
python scripts/study_costcap.py --with-refused --symbols <alle zwölf>

# Tests und Linter
python -m pytest tests/ -q
python -m ruff check src/ tests/ scripts/
```

**[FAKT] Prozesse auf dieser Maschine stoppen** (Git-Bash-`pkill` funktioniert nicht):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*papertrade.py*" } | Stop-Process -Force
```

---

## 15. Umgebung

**[FAKT]**

| | |
|---|---|
| Betriebssystem | Windows 11 Home 10.0.26300 |
| Python (Projekt) | 3.14.2 |
| Python (WSL2 Ubuntu 26.04) | 3.14, **ohne pip**, sudo passwortgeschützt — dort ist nichts installierbar |
| Kernbibliotheken | pandas 3.0.6 · numpy 2.5.3 · scikit-learn 1.9.1 · scipy 1.18.1 · LightGBM 4.7.0 · pyarrow 25.0.1 · duckdb 1.5.6 · ccxt 4.5.84 · pydantic 2.13.5 · FastAPI 0.141.1 · anthropic 1.9.0 |
| Test/Qualität | pytest 9.1.1 · hypothesis 6.168.3 · pytest-socket 0.8.1 · ruff 0.16.9 |
| Freqtrade-venv | freqtrade 2026.9 · TA-Lib 0.8.1 · XGBoost 3.4.1 |
| **Wichtig** | Für den gesamten ML-Stack existieren **cp314-Wheels**. Eine frühere Notiz, die das Gegenteil behauptete, war falsch. |

---

## 16. Glossar

| Begriff | Bedeutung |
|---|---|
| **R** | Vielfaches des riskierten Betrags. +1 R = der Trade hat so viel verdient, wie bei Stop verloren worden wäre. Die einzige Skala, auf der Trades hier verglichen werden. |
| **Maut / Toll** | Round-Trip-Transaktionskosten. |
| **Brutto** | Reine Preisbewegung, vor Gebühren. |
| **Netto** | Nach Gebühren und Funding. |
| **Basisrate** | Was ein ahnungsloses Verfahren auf denselben Zeilen erreicht. Der eigentliche Gegner. |
| **Testfenster** | Wiederholt gelesene Daten. Jede Zahl darauf ist ein Kandidat, nie ein Urteil. |
| **Prüffenster / Holdout** | Nie angesehene Daten. 0 Konsultationen. |
| **Arm** | Eine konkrete Hypothese mit Zahlen. 87 verschiedene. |
| **Familie** | Eine Klasse von Hypothesen. 16 erledigt, 1 nicht testbar. |
| **Champion** | Die aktuell beste belegte Konfiguration. Heute: −0,0340 R. |
| **Lauf-Signatur** | Hash aus Kapital, Setups, Kostendeckel, Zeitrahmen. Ändert sie sich, verwaisen gespeicherte Signale. |
| **Replay vs. live** | Replay = über bereits geschehene Bars; live = Begründung vor dem Ergebnis auf Platte. Werden nie gemischt. |

---

## 17. Zusammenfassung, Stand 07.10.2026

1. **[GEMESSEN]** 21 Familien (20 erledigt, 1 nicht testbar): **kein belegter Vorteil in
   der Richtungsvorhersage.** Neu dazu und alle vier negativ: Meta-Labeling (E1), die
   Haltezone (E2), die Ausgangspolitik (E3) und der Carry nach voller Kostenrechnung (E6).
   Bei E3 und E6 sind es die schärferen Formen: E3.3 ist *zuverlässig schlechter* als die
   bestehende Politik, und E6 passierte als Erstes im Projekt ein korrigiertes Intervall
   ohne Null — und fiel am Replikationstor mit gekipptem Vorzeichen.
2. **[GEMESSEN]** Auf der gemessenen Börse ist der grösste belegte Einstiegsvorsprung
   **3,8× kleiner als deren billigste Maut.** **Aber auf einer anderen Venue ist die ganze
   Taker/Taker-Runde auf BTC 22× *kleiner* als dieser Vorsprung** (0,0005 % gegen 0,0106 %).
   Die Maut ist damit nicht mehr der Grund, warum es nicht gehen kann — ob es geht, ist
   offen und heisst E0.
3. **[GEMESSEN]** Der Kostendeckel ist jetzt vollständig belegt, nicht nur arithmetisch:
   über 12 Märkte und 43 727 Signale haben billige Trades **besseres Brutto**
   (+0,0561 R, **[+0,017; +0,097]**, Null ausgeschlossen). Ein billiger Trade läuft bei
   **−0,0097 R**. **Trotzdem kein Vorteil:** R je Trade bei Deckel 0,08 ist +0,0107 mit
   [−0,041; +0,061].
4. **[GEMESSEN]** Funding-Carry ist real und schrumpft — auf gemeinsamem Kalenderfenster in
   **11 von 12** Märkten und in beiden Venue-Gruppen. Das sind wegen der Korrelation **eine**
   Beobachtung, nicht zwölf. Selbst bei perfekter Voraussicht schliesst sie ~1 % der Lücke.
5. **[GEMESSEN]** Das neue Ziel verlangt bei 3 % Risiko und 413 Trades **+0,243 R je Trade**,
   also 44,3 % Trefferquote gegen gemessene 32,5 %. Anders als das alte Ziel ist das
   **nicht** mehr als das physikalisch Mögliche — es ist unbelegt, nicht unmöglich.
   Zielchance auf der gemessenen Verteilung über 20 000 Pfade: **0,00 %**, bei jedem Risiko.
6. **[GEMESSEN]** Hebel ist kein Weg dorthin. 1× und 3× ändern nichts, ab 5× liquidieren
   37 % der Pfade, bei 10× 98 %, bei 15× alle — und die Zielchance bleibt durchweg 0,00 %.
7. **[FAKT]** Die eigentliche Leistung des Projekts ist der Apparat, der inzwischen **zehn**
   Scheinfunde gefangen hat, bevor sie geglaubt wurden. Die zwei neuesten sind die grössten:
   ein `max_adverse_r` von 147,88 R, das Bewegung nach dem Ausstieg mitzählte, und ein
   Modell, das **+1018 %** meldete, weil seine Merkmale die Kerze kannten, die sie handeln.
8. **[GEMESSEN]** Die Bewertung, die das System heute als Zuversicht behandelt, ist keine.
   Roh ist `rating/100` stark überzuversichtlich — im Band 0,90–1,00 sagt sie 0,946 und
   beobachtet **0,373**. Kalibriert ist sie von der Basisquote **nicht zu trennen**
   (gepaart −0,00005 mit [−0,00011; +0,00001]). `calibration_proven` bleibt zu, aber der
   Grund hat gewechselt: nicht Datenmangel, sondern **in der Zahl steckt nichts**. Mehr
   Fälle ändern das nicht.
9. **[GEMESSEN]** Alle **drei** Ablehnungsregeln sind über 12 Märkte und 41 382 Signale
   bestätigt — jede abgelehnte Population ist **brutto** negativ mit einem Intervall ohne
   Null. Die Regeln lehnen Trades ab, die Geld verlieren, *bevor* eine Gebühr anfällt.
   Unbequem dabei: der Brutto-Vorteil der **genommenen** Population spannt jetzt selbst
   über die Null (+0,0080 mit [−0,022; +0,039]). Jede Erweiterung der Stichprobe hat ihn
   Richtung Null bewegt.
10. **[GEMESSEN]** Die Maker-Annahme ist teurer als die Maker-Gebühr. Je ~17 s verschwinden
    **9,5 % (LINK) bis 49,2 % (ETH)** der ruhenden Orders, ohne dass der Preis sie erreicht
    hat. Und 1 000 USD sind **200 % von XRPs** Antrittsvolumen — dort kann ein Auftrag
    dieser Grösse gar nicht als Maker am besten Preis liegen. Die 0 % Maker-Gebühr ist real;
    die Maker-*Ausführung* ist es nicht.
11. **[GEMESSEN]** Die FreqAI-Basislinie ist repariert und verliert zuverlässig: 15 624
    Trades, **−0,58 %**, Profit-Faktor 0,35, **526 Verlusttage von 579**, p-Wert des
    mittleren Gewinns 0. Der alte „Vergleich" verglich nichts — der Basislauf endete am
    *Geld* statt am Fenster, und `identifier` hatte 74 Folds lang fremde Modelle
    stillschweigend wiederverwendet.
12. **[FAKT]** Die eigentliche Leistung des Projekts ist der Apparat, der inzwischen
    **zwölf** Scheinfunde gefangen hat, bevor sie geglaubt wurden. Die beiden neuesten
    stammen aus *dieser* Charge und wurden nicht von einem Test gefangen, sondern von einer
    Zahl, die nicht sein konnte: ein „Markout", der auf nichts bedingte und darum nur den
    Marktlauf wiederholte, und ein „belegter Fill" 394 bp vom Mid — ein Ask 4 % über dem
    Markt, der in 17 Sekunden nicht gehandelt wird.
13. **[GEMESSEN 07.10.2026]** **Der Funding-Carry ist kein Ertrag mehr** — und das war der
    letzte Posten in diesem Projekt mit positivem Vorzeichen
    (`audit/CARRY_NACH_KOSTEN.md`). Die blockierende Lücke ist geschlossen: acht Märkte mit
    Binance-Spot, -Perp und -Funding, je 33 013 Stundenkerzen. **Die Basis war nicht das
    Problem** — sie bewegt sich über 30 Tage um ±0,002 % und kehrt zurück, die Hypothese ist
    geprüft und widerlegt. **Die Maut war es:** 0,280 % je Runde gegen 0,2–0,5 % Funding in
    30 Tagen. Bei 180 Tagen Haltedauer passierte der Carry als erstes im Projekt das
    korrigierte Intervall (+1,5554 % [+0,2405; +3,0046]) — und fiel am **zweiten** Tor:
    Replikation früher +2,9374 % gegen später −0,1120 %, Verhältnis **−0,04×**, Vorzeichen
    gekippt. Ab 18.11.2024 bei keiner Haltedauer positiv, bei 30 Tagen zuverlässig negativ.
    Das ist der Fall, der belegt, warum **zwei** Tore nötig sind: eines allein hätte hier
    einen Kandidaten gemeldet.
14. **[GEMESSEN 07.10.2026]** **Zwei Blocker sind gefallen, und beide waren echt.** S7
    (dieses Orderbuch kann keinen Fill belegen) ist aufgehoben: `recentTrades` trägt die
    Order-Kennungen beider Seiten, also ist ein Fill belegbar statt folgerbar — 8,1 % belegt
    gefüllt, 90,2 % belegt storniert auf BTC. Und E4s Survivorship-Blocker ist nicht nur
    geprüft, sondern **gebaut**: 31 echte Perp-Delistings von 906, aus zwei öffentlichen
    Quellen. Das macht nichts profitabel — es nimmt zwei Gründe weg, aus denen eine Frage
    unbeantwortbar war.
15. **[GEMESSEN 07.10.2026]** **Die bestehende Ausstiegspolitik ist die beste der drei**
    (E3, `audit/E3_AUSGAENGE.md`). 7 255 Fälle, gepaart auf denselben Einstiegen: Stop+Ziel
    −0,0205 R, Stop+24h-Uhr −0,0824 R, Stop+2,0-ATR-Trail −0,0762 R mit einer gepaarten
    Differenz von **−0,0557 [−0,1123; −0,0060]** — zuverlässig *schlechter*. Das Ziel
    arbeitet: 31,1 % der Trades verlassen darüber, und beide Alternativen nehmen diese Tür
    weg. **Erstmals in diesem Projekt ist etwas, das das System schon tut, gegen eine
    benannte Alternative verteidigt** statt nur nicht widerlegt.
16. **[FAKT]** Und der unbequeme Teil bleibt unverkleinert: **nichts davon ist ein Vorteil.**
    Zwei Begründungen, mit denen ich Untersuchungen vorzeitig geschlossen hatte, sind
    gefallen — das macht vier Fragen wieder offen und beantwortet keine. Die Charge hat
    gemessen, repariert und zwei eigene Fehler kassiert. Einen Kandidaten hat sie nicht
    hervorgebracht, und das ist das Ergebnis, nicht sein Ausbleiben.

---

## 18. Der eine nächste Schritt — LÄUFT seit 07.10.2026, 17:39 UTC

**Er ist nicht mehr nur benannt, er läuft.** `scripts/collect_venue_tape.py`
nimmt seit 17:39 UTC Quotes **und Trades** auf sechs Märkten auf, mit lokaler
Empfangszeit, adaptivem Takt und mitgezählten Lücken. Und er hat seinen Zweck
schon zur Hälfte erfüllt, bevor die erste Stunde um war: **S7 ist aufgehoben**
(siehe oben), weil `recentTrades` die Order-Kennungen beider Seiten trägt.

Was damit noch offen ist: E0 Punkt 3 — überträgt sich ein Signal, das auf der
alten Börse entsteht, auf die neue? Das braucht die vollen elf Stunden und
mehr als einen Markt.

Der Schritt, wie er hier stand:

> **Die parallele, zeitgestempelte Aufnahme von Quotes _und Trades_ auf BTC und ETH über
> beide Venues starten — und zwar mit dem Trade-Tape, nicht nur dem Buch.**

**Warum dieser und kein anderer.** Drei offene Punkte hängen an derselben Aufnahme, und
keiner von ihnen kommt ohne sie weiter:

* **E0 Punkt 3** — ob ein Signal, das auf der alten Börse entsteht, auf der neuen
  überhaupt noch ausführbar ist. Ohne das ist die gemessene Kostensenkung (22× unter dem
  Vorsprung auf BTC) interessant und nicht entscheidend.
* **S7** — ohne Trade-Tape lässt sich in diesem Buch eine Teilausführung nicht von einer
  Teil-Storno trennen. 33 von 41 „Fills" lagen an nie erreichten Preisen. Damit gibt es
  keinen Markout, und ohne Markout keine Aussage über adverse Selektion.
* **E5** — der Orderflow-Arm wartet ohnehin auf genau diesen Collector.

**Was er ausdrücklich nicht ist.** Keine Order, kein Kapital, kein Schlüssel mit
Handelsrecht. Die Venue bleibt Daten- und Shadow-Quelle, bis Kontoberechtigung,
Orderschutz und tatsächliche Handelsrechte einen eigenen Review bestanden haben — und der
wird nicht dadurch vorbereitet, dass Schutzregeln still ausgeschaltet werden.

**Und was gleichzeitig weiterläuft, ohne diesen Schritt zu blockieren:** der FreqAI-Arm
(S4) rechnet zu Ende, und der Papierhändler sammelt die einzige Vorwärts-Evidenz, die es
gibt — bei ~1,9 Trades/Tag.

**Kein positiver Kandidat ist ebenfalls ein abgeschlossenes Ergebnis dieser Charge.**
Diese Charge hat keinen. E1 nicht belegt, E2 nicht belegt, die Kalibrierung ohne Inhalt,
die Basislinie zuverlässig negativ. Das ist der Stand, und er wird hier nicht
freundlicher formuliert, als er ist.
