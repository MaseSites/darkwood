# E20 — Market Making am Touch auf Lighter: was 72 Minuten feine Aufnahme hergeben

**Datum:** 20.10.2026
**Daten:** `data/quarantine/venue_tape/{BTC,ETH,SOL}/` — Buckets `1792429200000`
und `1792432800000` (19.10., ~2.35 s Kadenz, 72.3 / 72.3 / 68.2 Minuten).
**Apparat:** acht Agenten, vier Messungen mit je einer adversariellen Gegenprüfung.
**Ergebnis der Gegenprüfung: alle vier Messungen `haelt = False`.** Jede trug
echte Fehler. Was unten steht, ist der korrigierte Stand.

---

## 1. Die Frage, und warum sie offen war

Market Making ist in diesem Projekt die einzige Strategiefamilie, die nicht
widerlegt ist. Alle anderen sind an den Gebühren gestorben: der Einstiegs-Edge
war kleiner als der Zoll. Lighter nimmt fast keine Gebühren, also war das
Argument hier nicht anwendbar — und damit die Familie offen, nicht gültig.

Entschieden werden konnte sie bisher nicht, weil das Buch alle **30 Sekunden**
abgetastet wurde. Die Standzeit einer Quote liegt weit darunter und war damit
grundsätzlich unbeobachtbar. Die feine Aufnahme sollte das ändern.

---

## 2. Was gemessen werden konnte

| Grösse | Wert | Intervall | Quelle |
|---|---|---|---|
| Touch-Spread BTC | **0.0244 bp** (2 Ticks) | p25 0.0122 / p75 0.2193 | eigene Nachmessung |
| Touch-Spread ETH | **0.4585 bp** | p25 0.2910 / p75 0.5846 | eigene Nachmessung |
| Touch-Spread SOL | **0.4807 bp** | p25 0.1925 / p75 0.6734 | eigene Nachmessung |
| Angebotenes Touch-Notional, das handelt | **2.880 %** | [2.396, 3.444] Zeit-Block-Bootstrap | korrigiert von 2.516 % |
| — je Markt | BTC 2.97 / ETH 2.56 / SOL 3.41 % | streut kaum | " |
| Fuellquote der Touch-Orders (Stückzahl) | **27.38 %** | [25.47, 29.27] | korrigiert von 47.15 % |
| Mediane Grösse storniert ÷ gefüllt (BTC) | **18.65×** | — | hält |
| Touch-Leben, die genau EIN Raster dauern | **93.2 %** | 13188/14145 | korrigiert von 51.4 % |
| `maker_fee` fehlt im Trade-Band | **4.84 %** | 2450/50648 | eigene Nachmessung |

### Die Gebühreneinheit, aufgelöst

Das Trade-Band trägt `maker_fee` als ganzzahligen Code 28–50 (28, 32, 34, 36,
38, 40, 50), der **nicht** mit `usd_amount` skaliert (Mittel 35.91 bei <50 USD
gegen 29.34 bei >1000 USD) — also eine Staffel je Konto, kein Betrag.

Die Marktkonfiguration (`/api/v1/orderBooks`) nennt
`maker_fee: "0.0000"`, `taker_fee: "0.0000"`, beide `enabled`, bei
`liquidation_fee: "1.0000"` als Massstab — vier Dezimalstellen in Prozent.

Beides zusammen legt die Einheit fest, ohne sie zu raten:

| Kandidat | Code 28 ergäbe | Konfiguration zeigte | passt? |
|---|---|---|---|
| 1e-5 | 2.8 bp | `0.0280` | nein |
| 1e-6 | 0.28 bp | `0.0028` | nein |
| **1e-7** | **0.028 bp** | `0.0000` | **ja** |

Also rund **0.028 bp (Code 28) bis 0.050 bp (Code 50) je Seite.**

---

## 3. Was das Urteil trägt — und was es NICHT ist

**Die Gebühr ist hier nicht die bindende Grösse.** Auf ETH und SOL steht einem
halben Spread von ~0.23 bp eine Gebühr von 0.028–0.050 bp gegenüber, ein
Faktor 5–8 zugunsten des Market Makers. Das ist der erste Fall in diesem
Projekt, in dem der Zoll die Rechnung nicht entscheidet.

**Bindend ist, dass man nicht auf Grösse gefüllt wird.** Von 119.2 Mio USD, die
in 72 Minuten am Touch angeboten wurden, handelten 3.4 Mio — 2.880 %. Die
restlichen 97 % wurden zurückgezogen. Diese Zahl ist deshalb belastbar, weil sie
als einzige über die drei Märkte kaum streut (2.56–3.41 %), während die
Stückzahl-Fuellquote zwischen 13 % und 44 % schwankt.

Der Grund ist direkt gemessen: auf BTC ist die mediane gefüllte Touch-Order
**18.65× kleiner** als die mediane stornierte. Was füllt, sind Krümel; was
Grösse trägt, wird gezogen.

**BTC ist tot, ETH und SOL sind es nicht.** Ein halber Spread von 0.0122 bp
trägt auf BTC keine Gebühr und keine adverse Selektion. Auf ETH/SOL ist der
halbe Spread ein Faktor 19 grösser, und die Rechnung bleibt offen.

---

## 4. Was dieser Apparat grundsätzlich nicht beantworten kann

**Die Standzeit einer Quote.** 93.2 % der beobachteten Touch-Leben dauern genau
einen Rasterschritt. Der berichtete „Median 2.36 s" ist die mittlere Kadenz
(2.356 s) auf drei Stellen genau — **die Messung beschreibt den Apparat, nicht
den Markt.** Die wahre Standzeit liegt unter dem Raster und ist nach oben
begrenzt, mehr nicht. Das ist in diesem Projekt der vierte Fall desselben
Musters und wurde hier nur gefunden, weil eine Gegenprüfung danach gesucht hat.

**Feiner geht es mit Abfragen nicht.** Mit `--book-every 1` lief die Aufnahme am
20.10. genau 70 Sekunden und sammelte danach 8.190 Fehler „HTTP 405" am Stück,
während die Aufgabe weiter auf „Running" stand. Nach 45 s Ruhe antwortete die
API normal: eine Drosselung, keine Sperre. Gestern erreichte derselbe Aufruf nur
2.35 s (~100 Anfragen/min) und lief 72 Minuten durch; heute erreichte er die
bestellte 1 s (~178/min) und war nach einer Minute draussen. Die Grenze liegt
dazwischen; 2.5 s ist jetzt eingestellt und mit 0 Fehlern über eine Minute
nachgemessen (23 Bücher/min auf BTC).

**Der Stichprobenrahmen fehlt um 39–69 %**, nicht um die zunächst berichteten
1.4–3.8 %. Maker-Orders, die zwischen zwei Schnappschüssen entstehen und
vergehen, hinterlassen in keinem der beiden Instrumente eine Spur, wenn sie nie
handeln. Jede Standzeit oben ist darum zu freundlich, jede Stornoquote zu
niedrig.

Für die Standzeitfrage braucht es den **Websocket-Strom**, nicht diesen Sammler.

---

## 5. Fehler, die die Gegenprüfung gefunden hat

Festgehalten, weil sie Muster sind und nicht Einzelfälle:

1. **Ein erfundener Nullwert.** `t.get('maker_fee', 0)` machte aus den 4.84 %
   fehlenden Feldern stillschweigend die Gebühr 0 — und daraus den Befund
   „654 gebührenfreie Konten (13.81 %)". Eine fehlende Messung wurde zu einer
   gemessenen Null.
2. **Vier Wege, die ein Weg waren.** „47.17 / 47.15 / 46.88 / 45.26 % über vier
   unabhängige Wege" benutzten alle dasselbe Kriterium `v > 0` über verschieden
   abgegrenzte Populationen. Ihre Übereinstimmung prüfte die Abgrenzung, nicht
   das Kriterium.
3. **Ein Holdout, der keiner war.** Die Trenngrenze lag exakt auf der Grenze
   zwischen den zwei Aufnahmedateien, und der Gradient, aus dem das Kriterium
   stammte, war über die Gesamtpopulation gerechnet — Holdout eingeschlossen.
4. **Eine lebende Datei in der Stichprobe.** Bucket `1792476000000` wuchs
   während der Messung. Er hat 61 Zeilen und stammt aus dem abgestürzten Lauf.
5. **Prozentwerte auf 0 bis 2 Beobachtungen.** Die Überlebenszeilen bei 10/30/60 s
   sind 1–34 Orders von 14156 und dürfen keine Intervalle tragen.
6. **Ein Test, der nicht fehlschlagen kann.** Eine Prüfung filterte vorher auf
   genau die Bedingung, die sie danach bestätigte.
7. **Zu enge Intervalle trotz befolgter Regel.** Geclustert wurde auf Zeit — aber
   7 von 221 Maker-Konten liefern 50.1 % aller Touch-Füllungen. Die Konto-Achse
   fehlte.

---

## 6. Urteil

**Market Making am Touch, naive Variante (passiv stehen und warten): gefallen
auf BTC, unentschieden auf ETH/SOL.**

Nicht gefallen ist die Familie. Nicht gemessen sind:
hinter dem Touch quoten, im Sekundenbereich nachziehen, und die Frage, ob man
auf ETH/SOL überhaupt Grösse platzieren kann, ohne sofort advers selektiert zu
werden.

**Keine Profitabilitätsbehauptung.** Die eine Zahl, die eine Strategie tragen
müsste — ob man auf Grösse gefüllt wird, ohne dass der Preis gegen einen läuft —
ist mit diesem Instrument nicht messbar.
