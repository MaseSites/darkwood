# E5 / P26 — Der Streaming-Collector ist nicht baubar, und der Host, der liefert, ist der falsche

Reproduktion:

```bash
python scripts/probe_futures_streams.py
```

Stand 09.10.2026, 08:24–08:27 UTC. Commit `546a3bc`.
**Nur gelesen. Kein Schlüssel, keine Order.**

---

## 1. Was der Auftrag verlangt und was erfüllt ist

Phase 3 verlangt zuerst, *„den aktuellen USDⓈ-M-Futures-Endpunkt und die
aktuellen Payloads anhand der offiziellen Dokumentation zu verifizieren"* und
ausdrücklich *„nicht ungeprüft Spot-API-Beispiele zu kopieren"*.

**Erfüllt, und das ist echter Fortschritt** — die Prozedur liegt jetzt wörtlich
vor, in der Futures-Fassung:

```
3. Snapshot: https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000
4. "Drop any event where `u` is < `lastUpdateId` in the snapshot."
5. "The first processed event should have `U` <= `lastUpdateId`
    AND `u` >= `lastUpdateId`"
6. "each new event's `pu` should be equal to the previous event's `u`,
    otherwise initialize the process from step 3."
7./8. Mengen sind absolut je Preisniveau; Menge 0 heisst Niveau entfernen.
9. Ein Entfernen eines lokal nicht vorhandenen Niveaus ist normal.
```

**`pu` ist der Unterschied zur Spot-Fassung.** Spot kennt das Feld nicht und
prüft `U == voriges u + 1`. Wer das Spot-Verfahren auf Futures anwendet,
invalidiert sein Buch entweder dauernd oder nie. Genau davor warnt der
Auftrag, und die Warnung trifft zu.

### Empirisch belegte Payloads

Die Doku-Seite zu den Feldern liess sich nicht abrufen, also wurde gegen die
Quelle selbst geprüft statt gegen mein Gedächtnis:

| | Felder |
|---|---|
| REST `fapi/v1/depth` | `E`, `T`, `asks`, `bids`, `lastUpdateId` |
| `aggTrade` | `E`, `T`, `a`, `e`, `f`, `l`, `m`, `nq`, `p`, `q`, `s`, `st` |

**`nq` und `st` kannte der bestehende Polling-Collector nicht** — er behält
`a, p, q, T, m`. Für dessen Zweck genügt das; festgehalten ist es trotzdem.

## 2. Der Blocker, in vier Schritten eingegrenzt

| Prüfung | Ergebnis |
|---|---|
| REST `fapi.binance.com` | **funktioniert** — Snapshot mit `lastUpdateId=11773523093224` |
| DNS aller Stream-Hosts | **löst auf** — 52.193.178.51 / 54.250.27.199 / 3.165.255.48 |
| WebSocket-Handshake gegen `fstream.binance.com` | **gelingt** — `Upgrade: websocket`, gültiges `Sec-WebSocket-Accept`, `permessage-deflate` verhandelt |
| Client selbst | **funktioniert** — neutraler Echo-Dienst antwortet |
| `SUBSCRIBE btcusdt@aggTrade` | **angenommen** — `{"result":null,"id":1}`, die dokumentierte Erfolgsantwort |
| **Marktdaten danach** | **null in 12 s** |

Vier Pfade geprüft, alle stumm: `/stream?streams=`, `/public/stream?streams=`,
`/ws/`, `/public/ws/`. Die beiden Doku-Seiten nennen **verschiedene** Pfade
(eine mit, eine ohne `/public/`) — der Unterschied ist nicht die Ursache.

**Gegenprobe, wie viel hätte kommen müssen:** 1 000 REST-`aggTrades` spannen
126,9 s, also **7,9 Trades/s**. In 12 s wären das rund **95 Nachrichten**. Null
ist keine ruhige Minute.

Binance nimmt die Verbindung an, bestätigt das Abonnement und liefert nichts.
Das ist eine serverseitige Beschränkung für diese IP, kein Fehler im Code.

## 3. Und der Host, der liefert, ist nicht der Produktions-Stream

`stream.binancefuture.com` ist als gleichwertiger Endpunkt dokumentiert und
**liefert** — 24 `aggTrades` in 20 s. Das sah nach der Lösung aus.

Es ist keine:

| | Stream-Host | REST Mainnet |
|---|---|---|
| Preise | 82 571,90 – **82 573,30** | 82 569,60 – **82 573,30** |
| **Preisabstand** | **0,00 USDT** | |
| `aggTrade`-Kennungen | **314 122 791 – 314 122 814** | **3 480 283 205 – 3 480 283 224** |
| Trades/s | 1,2 | 7,9 |

**Die Preise stimmen auf den Cent, die Kennungen unterscheiden sich um Faktor
11, und die Rate ist ein Sechstel.**

Das ist die gefährlichste Form eines Fehlers, die dieses Projekt kennt: die
Daten sehen richtig aus. Eine Preisprüfung hätte ihn **nie** gefunden. Was auf
diesem Strom falsch wäre:

* Jede Lückenzählung über `a` — ein anderer Kennraum.
* Jeder Id-Join gegen Mainnet-REST — er trifft fremde Trades.
* Jede Buch-Sequenzprüfung über `U`/`u`/`pu` gegen einen Mainnet-Snapshot —
  das Verfahren aus Abschnitt 1 verlangt genau diesen Vergleich und würde
  dauerhaft invalidieren.
* Jede Aussage über Empfangslatenz oder Vorlauf — bei einem Sechstel der
  Trades fehlt die Mehrheit der Ereignisse.

Und für **P26** wäre es wertlos in der Sache: die ganze Frage ist, ob eine
Sekunde Vorlauf echt oder ein Uhrenversatz ist. Ein Strom, der 85 % der
Ereignisse nicht zeigt, kann das nicht entscheiden.

## 4. Befund

**E5 bleibt blockiert, und P26 mit ihm.** Der Blocker ist jetzt präzise
benannt und hat sich gegenüber der früheren Fassung verschoben:

> Vorher: „es gibt keinen Streaming-Collector."
> Jetzt: **„Produktions-WebSocket-Marktdaten werden an diese IP nicht
> ausgeliefert, und der Host, der liefert, führt einen anderen Kennraum und
> ein Sechstel der Ereignisse."**

Das ist kein Bauproblem. Ein Collector mit Sequenzkontrolle, Reconnect,
Stale-Erkennung und Lückenmetriken ist in einem Tag geschrieben — er hätte
nur nichts zu lesen.

**Was ich nicht vorschlage:** einen Weg um die Beschränkung herum. Der
Forschungsauftrag verbietet die Umgehung von Börsenbedingungen, und ich halte
mich daran. Ob und wie der Zugang auf regulärem Weg herzustellen ist, ist eine
Entscheidung des Kontoinhabers mit seinem Anbieter und der Börse — nicht
meine.

**Was damit auch offen bleibt:** das Phase-1-Abnahmekriterium („ein absichtlich
eingeführter Fehler führt zu einem klaren ungültigen Status"). Es verlangt
Sequenz- und Stale-Zustände, die nur ein Streaming-Collector hat.

## 5. Was bestehen bleibt und nutzbar ist

Das **Polling** funktioniert. Die beiden Tape-Collectoren haben damit 11,00 h
Venue-Tape und 94,9 % Binance-Abdeckung aufgenommen, und `study_tape_fills.py`
hat daraus belegte Fills über einen Id-Join gezogen. Was Polling nicht kann,
steht in `TAPE_VOLLE_ABDECKUNG.md`: die Lücke auf der neuen Venue ist nicht
zählbar, und ein Versatz von einer Sekunde ist nicht von einem Uhrenversatz
zu trennen.

## 6. Grenzen dieser Prüfung

**Ein Zeitpunkt, eine IP.** Gemessen am 09.10.2026 zwischen 08:24 und 08:27
UTC von dieser Maschine. Eine serverseitige Beschränkung kann sich ändern; die
Prüfung ist mit `scripts/probe_futures_streams.py` in zwanzig Sekunden
wiederholbar.

**Ein Symbol, drei Streams.** BTCUSDT auf `depth@100ms`, `aggTrade` und
`bookTicker`. Dass ein anderes Symbol anders behandelt würde, ist
unwahrscheinlich und nicht geprüft.

**Der Kennraum-Befund ist eine Beobachtung, keine Erklärung.** Warum
`stream.binancefuture.com` einen anderen Kennraum führt, sagen diese Daten
nicht. Belegt ist nur, dass er einen anderen führt — und das genügt, um ihn
für diese Forschung auszuschliessen.
