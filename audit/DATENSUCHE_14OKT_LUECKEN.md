## Drei Dinge, die in den acht Familien nicht vorkommen

Vorbemerkung, damit die Liste nicht falsch gelesen wird: ich habe vorher nachgesehen, was schon auf der Platte liegt — `data/external/` (CoinMetrics 9 Assets, FRED, DefiLlama-Stablecoins), `data/derivatives/` (Open Interest, Long/Short-Account-Ratio, 4 Märkte), `data/flow/` (Taker-Volumen H1, 2 Märkte), `data/sentiment.parquet`. Die acht Familien sind also nicht nur durchsucht, sie sind teilweise schon gekauft und verbaut. Alles, was ich unten nenne, ist eine **andere Art von Daten**, nicht ein weiteres Merkmal derselben Art.

---

### 1. Fremde Konten statt eigener Kurse: die öffentlichen Positions- und Fill-Historien einzelner Adressen

**Was fehlt.** Alle 124 Registereinträge beantworten dieselbe Frage: *habe ich einen Vorteil?* Niemand hat je gefragt: *hat ihn überhaupt irgendjemand?* Auf Hyperliquid ist jede Position, jeder Fill und jedes PnL jeder Adresse öffentlich abfragbar — `clearinghouseState` (Positionen, Hebel, Liquidationspreis) und `userFillsByTime` (Fill-Historie, paginiert) über `https://api.hyperliquid.xyz/info`, dazu die Leaderboard-Adressen. Das ist keine Marktdatenfamilie, das ist eine Teilnehmerdatenbank.

**Die Frage, die OHLCV nicht stellen kann.** Gibt es eine Kohorte von Adressen, deren Beta-bereinigtes, kostenbereinigtes PnL über getrennte Zeitfenster **persistiert** — und sagt deren aggregierte Netto-Position die nächsten N Stunden voraus, nachdem BTC-Beta abgezogen ist? Aus Preisen ist das prinzipiell nicht rekonstruierbar: wer gehalten hat und mit welcher Bilanz, steht in keiner Kerze.

**Warum das ernsthaft ist.** Beide Ausgänge sind entscheidungsreif. Findet sich keine persistente Kohorte, ist das das stärkste Schlussargument, das dieses Projekt je bekommen kann — und es ist eins, das Befund 3 (gehebeltes Beta) auf den ganzen Markt verallgemeinert statt nur auf uns. Findet sich eine, ist zum ersten Mal belegt, dass der Markt überhaupt schlagbar ist, und man weiß, in welcher Zeitskala.

**Fallstricke, vorher benannt.** `userFills` liefert nur die 10.000 jüngsten Fills je Adresse (max. 2.000 pro Antwort) — tiefe Historie muss vorwärts gesammelt werden, rückwärts ist sie für aktive Adressen verloren. Leaderboards sind maximal survivorship-verseucht: die Kohorte muss aus einer *Punkt-in-Zeit*-Adressliste gebildet werden, nicht aus der heutigen Rangliste, sonst misst man dasselbe wie eine Querschnittsstudie auf den zwölf Überlebenden. Und: selbst eine echte Gewinnerkohorte ist nicht notwendig kopierbar — wenn ihr Vorteil Market-Making ist, ist er bei unserer Größe und unserem Gebührenrang nicht erreichbar. Die Messung bleibt trotzdem wertvoll, die Kopie ist die zweite Frage.

**Kosten.** Null Euro, nur Sammelzeit. Vorwärtssammlung ab sofort, sinnvolle Auswertung nach Wochen, nicht nach Tagen.

### 2. Die eigenen Ausführungsberichte: was *unsere* Order wirklich tut

**Was fehlt.** Jede Fill-Annahme im Replay ist aus einem **fremden** Buch geschätzt. Der Befund dazu steht schon im Gedächtnis: bis zu 49 % der ruhenden Orders verschwinden je 17 s unerreicht; nur 12,4 % der Orders an der Berührung füllen überhaupt; 1.000 USD übersteigen die ganze XRP-Berührung. Ein öffentliches Buch kann einen Fill prinzipiell nicht beweisen — es enthält unsere Queue-Position nicht und kann sie nicht enthalten.

**Die Frage.** Welcher Anteil unserer *eigenen* ruhenden Maker-Orders füllt innerhalb von N Sekunden, bei unserer Klippengröße, und mit welchem Markout nach 1/5/30 Minuten? Markout ist dabei der eigentliche Punkt: er misst, ob wir systematisch *ausgewählt* werden — also ob die Fills, die wir bekommen, genau die schlechten sind. Das ist aus keiner öffentlichen Quelle ableitbar.

**Bezugsquelle.** Ein echtes Konto mit Kleinstgröße (10–20 USDT je Klippe), privater WS-Kanal: Bybit v5 `execution`, oder Hyperliquid `userFills` auf die eigene Adresse. Keine historischen Daten zu kaufen, die Daten entstehen beim Senden.

**Und jetzt die Ehrlichkeit, die diesen Kandidaten klein macht.** `audit/TRIAL_LEDGER.csv`, Zeile `gebuehr_minus_25`, sagt: **bei Gebühr null sind es +0,0151 R**. Das sind 2,8 % der benötigten 0,54 R. Dieser Kandidat kann die Zahl also nicht retten — er kann sie nur **senken**. Genau deshalb ist er trotzdem wertvoll: er ist der einzige, der die gemessene −0,0129 R als zu *optimistisch* entlarven könnte, und die Geschichte dieses Projekts besteht zu einem guten Teil aus solchen Entlarvungen.

### 3. Optionskurse als *Instrument*, nicht als Vorhersage

**Was fehlt.** Die Familie „options" wurde als Signalquelle durchsucht (IV, Skew, Put/Call als Prädiktoren). Die andere Frage ist nie gestellt worden: dieselbe richtungslose Entscheidung, aber mit konvexer Auszahlung statt mit 20x Perp und 1R-Stop. Dafür braucht es **ausführbare Geld-/Briefkurse** historischer Optionen, nicht IV-Flächen.

**Die Frage, präzise.** Für denselben 4–8-Stunden-Richtungsaufruf mit nachweislich null Brutto-Vorteil: ist der Hausanteil einer 0,25-Delta-Option (halber Spread rein + halber Spread raus + Theta über die Haltedauer) **kleiner** als der eines 20x-Perps mit 1R-Stop (0,105 % Round Trip plus Stop-Pfadkosten)? Mit OHLCV und Funding ist das nicht beantwortbar — es hängt an Spreads, die nirgends in unseren Daten stehen.

**Bezugsquelle, konkret und bezahlbar.** CryptoStruct verkauft Deribit-Options-Chain-Tage einzeln (1 €/Instrumententag bzw. Tagesbündel einer ganzen Kette, Abdeckung ab Okt 2023, Gratis-Sample je Kette) — damit lässt sich die Frage auf 100–200 ausgewählten Tagen für ein paar hundert Euro entscheiden. Alternativ Tardis.dev `options_chain` (Deribit ab 2019-03-30, Options-Plan ab 350 $/Monat akademisch) oder Amberdata `options/order-book-snapshots/{instrument}/historical`.

**Was dieser Kandidat ist und was nicht.** Er erzeugt **keinen** Vorteil. Konvexität ändert keine Erwartung, sie ändert die Form. Er ist der einzige der drei, der das 16-Tage-Ziel arithmetisch überhaupt erreichbar machen könnte — und zwar genau so, wie ein Lotterielos ein Ziel erreichbar macht: mit negativer Erwartung und einem fetten rechten Rand. Wenn die Messung sagt „der Optionsanteil ist größer als der Perp-Anteil", ist die Zielfrage endgültig geschlossen. Auch das ist ein Ergebnis.

**Nicht-Kandidat, ausdrücklich:** der E4-Blocker (Stunden-/Tageskerzen für das Punkt-in-Zeit-Universum der 749 Perps, inkl. der delisteten aus `data.binance.vision`). Kostenlos, halb gebaut (`scripts/build_universe.py`, `data/universe/binance_um_perps.json`), und das Einzige, was *neue unabhängige Versuche kauft* statt welche zu verbrauchen. Aber es ist weder neu noch ungesucht: es steht als `status: blockiert_an_preisen` in `audit/EXPERIMENTS_NEXT.yaml` und fällt in die Familie „crosssection". Ich nenne es, weil es das billigste offene Datenstück ist — nicht, weil es jemand übersehen hätte.

**Was ich bewusst nicht vorschlage:** News-NLP, Social-Sentiment, Whale-Alerts, Orderflow-Imbalance-Varianten, LLM-auf-Schlagzeilen. Das sind alles Umlackierungen der Familien 1–8, und sie beantworten dieselbe Vorhersagefrage, die 35 Merkmale in zwei Familien bereits mit Korrelation 0,004 beantwortet haben.

---

## Die ehrliche Antwort

**Kein Überlebender bei 19 Kandidaten in acht Familien ist kein Pech. Es ist ein Befund.**

Bis zu dieser Suche war „uns fehlen nur die richtigen Daten" eine lebende Hypothese. Sie ist jetzt gemessen und tot. Damit haben drei *unabhängige* Suchprogramme dasselbe geliefert: 87 Arme auf den Daten → null. 32 Agenten über 24 Literaturansätze → null. 19 Datenkandidaten über acht Familien → null. Wenn drei verschiedene Suchverfahren dieselbe Null zurückgeben, ist die wahrscheinlichste Erklärung nicht, dass alle drei schlecht gesucht haben.

**Die Arithmetik des Ziels, ohne Beschönigung.** Das korrigierte Intervall reicht bis +0,0594 R. Das ist die *großzügigste* Zahl, die 7.335 Trades hergeben. Benötigt werden 0,54 R — das **Neunfache der Obergrenze**, nicht des Schätzers. Bei 1,9 Trades/Tag sind 16 Tage rund 30 Trades, also etwa +16 R kumuliert. Bei Erwartung null und einer Streuung von 1,0–1,3 R je Trade liegt das 2,3 bis 3,0 Standardabweichungen über null: grob **zwischen 1:80 und 1:650**. Das ist keine Strategie, das ist ein Einsatz. Und auf jedes Los werden 0,105 % Maut erhoben.

**Die Frist und die Forschung schließen einander aus.** In 16 Tagen entstehen ~30 Trades. 100 Vorwärtstrades brauchen ~52 Tage. Keine Messung, die in der Frist abschließbar ist, hat genug Trades, um irgendetwas zu entscheiden. Man kann die Frist haben oder die Forschung, nicht beides. Wer in diesen 16 Tagen „noch schnell etwas misst", misst Rauschen und wird es für ein Ergebnis halten.

**Das Fortsetzen hat inzwischen negativen Informationswert.** Bei 67 angemeldeten Vergleichen senkt jeder weitere Arm die Wahrscheinlichkeit, dass ein künftiges Positiv echt ist. Fünf Jahre Daten tragen ~45 unabhängige Versuche; 124 sind gelaufen. Versuch 125 ist nicht der, der es findet — er ist der, der die Korrektur weiter verschlechtert.

**Der eine positive Wert im ganzen Register ist gekauft, nicht verdient.** Die Vorwärts-+0,80 R sind Beta 1,0 zu BTC mit verlässlich negativem Residuum. Im Klartext: der gesamte realisierte Gewinn dieses Systems ist ohne das System erhältlich — durch Halten von BTC, zu niedrigeren Kosten, mit weniger beweglichen Teilen und ohne 0,105 % je Round Trip. Das ist der einzige Satz im ganzen Bericht, der sofort handlungsrelevant ist.

**Was dieses Projekt tatsächlich hergestellt hat, ist eine Schranke, keine Strategie.** 124 angemeldete Versuche, vorab registrierte Intervalle, eine gemessene Erwartung in ±0,09 R um null, eine vollständige Negativliste über acht Datenfamilien. Das ist ein sauberes, seltenes, ehrliches Ergebnis — der Wert liegt in seiner Qualität, nicht in einer Rettung. Die verbleibende Arbeit, die sich noch lohnt, sind genau die beiden Messungen oben, die **nur falsifizieren können** (eigene Fills, Adresskohorte), plus das Hinschreiben der geschlossenen Datenfamilie ins Register, damit niemand — auch ich nicht in drei Monaten — die acht Familien ein zweites Mal durchsucht.

Und die Entscheidung über die 12.075 USDT ist keine Forschungsfrage mehr. Die Handlung mit der besten bekannten Erwartung ist, sie nicht durch diese Maschine zu schicken.