---
typ: forschung
status: entschieden
aktualisiert: 2026-10-21
naechster_schritt: Tardis-Gratistage holen und den Heatmap-Renderer dagegen bauen, BEVOR ein Dauersammler startet
tags: [daten, gamma, liquiditaet, heatmap, volumenprofil, recherche]
---

# 📡 Datenquellen — was es gibt und was nicht

Vier gewünschte Chart-Ebenen, geprüft am 21.10.2026 mit vier Rechercheuren und
vier Gegenprüfern. Jeder Endpunkt wurde **aufgerufen**, nicht nur zitiert.

> [!important] Die Regel dahinter
> Eine erfundene Ebene im Chart wäre der schlimmste mögliche Fehler hier.
> Lieber eine Absage als eine hübsche Linie, die nichts misst.

## Kurzfassung

| Ebene | Machbar | Entscheidung |
|---|---|---|
| **Volumenprofil + VPOC** | ✅ ja | **gebaut** am 21.10. |
| **Echte Heatmap** | 🟡 teilweise | erst messen, dann sammeln |
| **Institutionelle Liquidität** | 🟡 teilweise | nur als das benennen, was es ist |
| **Gamma (GEX)** | 🟡 teilweise | **keine GEX-Linie**, nur OI je Strike |

---

## Volumenprofil + VPOC — gebaut

`data.binance.vision` legt je Markt und Tag ein ZIP mit allen aggregierten
Trades ab. Öffentlich, kein Schlüssel, alle zwölf Märkte, zurück bis 2020.

Gemessen auf BTCUSDT am 19.10.2026:

```
1'002'851 Trades, 147 Körbe
VPOC 82'200   VAL 81'860   VAH 82'630
Value Area deckt 70.4 % ab (Ziel 70 %)
am VPOC waren nur 40 % der Trades käufergetrieben
```

**Die Grenze, die ins Bild gehört:** das Archiv erscheint erst am Folgetag.
Vollständiges Profil bis gestern, der laufende Tag **gar nicht** aus dieser
Quelle. `fstream.binance.com` ist für diese Leitung stumm — zweiter
unabhängiger Befund nach [[🚨 Monitoring & Incidents]].

**Zwei Korrekturen am eigenen Code:**
- Der Kommentar „der stärkste Magnet" beim POC war eine Signalbehauptung ohne
  Beleg. Raus.
- Die alte Ebene heisst jetzt „Volumen-Näherung (aus Kerzen)". Sie verteilt
  das ganze Volumen einer Kerze auf deren Mittelpreis und darf den Namen
  „Volumenprofil" nicht tragen.

Körbe hängen an der **Preisgrössenordnung, nicht am Zoom**: ein POC, der sich
beim Hineinzoomen verschiebt, ist keine Eigenschaft des Marktes.

---

## Gamma — keine Linie, und der Grund ist hart

GEX misst: offene Kontrakte je Strike × Black-Scholes-Gamma × **ein Vorzeichen,
das nirgendwo in den Daten steht**. Welche Seite die Dealer halten, ist eine
Konvention, keine Messung.

Nachgerechnet, und das ist die entscheidende Zahl:

```
BTC brutto (alle Vorzeichen positiv)  571'341'394 USD pro 1 %
BTC netto  (übliche Konvention)       180'605'721 USD pro 1 %
```

**Das Vorzeichen entscheidet über zwei Drittel der angezeigten Zahl.** Eine
Grösse, die auf Knopfdruck das Vorzeichen wechselt, ist kein Chart-Layer,
sondern eine offene Frage.

Dazu: GEX im Verhältnis zum Perp-Tagesvolumen — BTC 1.64 %, ETH 0.24 %,
AVAX 0.030 %, XRP 0.024 %, SOL 0.018 %. Nur BTC liegt in einer Grössenordnung,
in der eine Absicherung die Tape überhaupt berühren *könnte*. „Könnte" ist
keine Messung.

**Welche Märkte gar keine Optionen haben — korrigiert:** nicht sieben, sondern
**fünf**: ADA, LINK, LTC, DOT, ATOM. BNB hat 122 Optionen auf Binance
(GEX = 0.155 % des Perp-Volumens), DOGE 24 (0.0011 %, Rauschen). Der erste
Bericht behauptete „gibt es nirgends", ohne Binance und Bybit abzufragen —
eine Nicht-Existenz zu melden, die man nicht geprüft hat, ist derselbe
Fehlertyp wie eine erfundene Linie, nur in die andere Richtung.

**Was gebaut werden darf, ohne eine Annahme:** Open Interest je Strike und
Call/Put-Verhältnis, nur BTC und ETH. Ein Aufruf
(`get_book_summary_by_currency`) liefert alle 886 BTC-Instrumente. Wenn
„Gamma eingezeichnet" eigentlich „wo liegen die grossen Strikes" heisst — und
das ist die wahrscheinlichste Lesart — gibt es das zu 100 % ohne Fiktion.

**Blocker für alles Weitere:** es gibt **kein öffentliches historisches Open
Interest**. Deribits Chart-Endpunkt liefert OHLCV ohne `open_interest`. GEX
lässt sich darum heute nicht als Feature gegen die nächsten Stunden messen.
Der einzige ehrliche Weg wäre, ab heute stündliche Snapshots wegzuschreiben
(ein Aufruf, ~400 KB, gratis) und in Monaten zu messen.

---

## Institutionelle Liquidität — das Etikett trägt nicht

Das Orderbuch ist **anonym**. Es gibt keine Möglichkeit, institutionelle von
privater Order zu unterscheiden. Was existiert und oft so genannt wird:

- Liquidationen (`forceOrders`)
- grosse Einzeltrades (`aggTrades` mit Grössenschwelle)
- Open-Interest-Sprünge
- CVD/Delta aus dem Trade-Tape

Das sind reale Messgrössen. Sie „institutionell" zu nennen, ist ein Etikett,
das man draufklebt — und genau das soll hier nicht passieren. Wenn diese
Ebene kommt, heisst sie, was sie misst: *grosse Trades*, *Liquidationen*.

---

## Echte Heatmap — erst messen, dann sammeln

Der Vorwärtsweg ist **bestätigt**: Diff-Strom + Schnappschuss,
`U <= lastUpdateId <= u`, danach `pu == vorheriges u`. Null Kettenbrüche in
zwei unabhängigen Läufen.

Kosten: 12 Märkte × 200 Preisstufen × 4 B × 86'400 s = **829 MB/Tag roh**,
71.4 KB/s Netz. Verzögerung: Median 66 ms auf drei Märkten, aber auf zwölf
fällt eine einzelne Parse-Schleife auf 260 ms zurück — **der Sammler darf im
Empfangs-Loop nicht parsen.**

**Die Reihenfolge ist die eigentliche Entscheidung.** Nicht ein Jahr sammeln
und dann sehen: die Ablage ist voll mit Kandidaten, die nach Monaten fielen
([[📊 Evidenzstand]]). Mit den Tardis-Gratistagen sind das rund **46
vollständige Tage echtes Preisstufen-Buch** über alle zwölf Märkte, mit
`is_snapshot`-Flag und jedem Delta. Also: Renderer dagegen bauen, prüfen ob
eine sichtbare Wand überhaupt etwas über die nächsten Minuten sagt, und
**erst bei einem Ja** den Dauersammler starten.

> Kosten des Umwegs: ein Download. Kosten des Verzichts: ein Jahr und 35 GB.

---

## Verwandt

[[📊 Evidenzstand]] · [[🧪 Experimentregister]] · [[📖 Forschungsquellen]] ·
[[🚨 Monitoring & Incidents]]
