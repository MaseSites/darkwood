# Pflichtenheft: was ein Kandidat erfüllen müsste

Stand 09.10.2026, 15:00 UTC. Jede Zahl unten ist **gemessen**, keine
geschätzt.

Dieses Dokument sagt nicht, *wie* man einen Vorteil findet. Es sagt, **woran
man erkennt, dass man einen hat** — und wie gross er sein muss, damit er für
das Ziel reicht. Nach 24 abgeschlossenen Familien ohne Kandidaten ist das die
nützlichere Form: statt „kein Vorteil gefunden" ein Ziel mit Zahlen.

---

## 1. Die Grenze, auf der das Ziel liegt

`(1 + Risiko · R)^n = 20`, über 182 Tage:

| Trades/Tag | n | **nötiges R bei 1 %** | bei 3 % *(Deckel)* |
|---|---|---|---|
| **1,9** ← gemessene Rate | 346 | **+0,8701** | +0,2900 |
| 3,0 | 546 | +0,5502 | +0,1834 |
| 5,0 | 910 | +0,3297 | +0,1099 |
| 10,0 | 1 820 | +0,1647 | +0,0549 |
| 20,0 | 3 640 | +0,0823 | +0,0274 |
| 50,0 | 9 100 | +0,0329 | +0,0110 |

**Jede Zeile ist ein gültiger Weg zum Ziel.** Mehr Trades senken das nötige R
je Trade — aber nicht beliebig, siehe Abschnitt 2 und 4.

Gemessen: **−0,0906 R** (2 734 Replay-Trades), bester je gefundener Arm
**−0,0340 R**.

## 2. Was das *Brutto* sein muss, nicht das Netto

| | |
|---|---|
| gemessene Maut je Runde | **0,280 %** des Notionals |
| gemessener Median-Stop | **1,3090 %** des Preises |
| **Maut in R** | **0,2139 R je Trade** |

Daraus die Brutto-Anforderung:

| | netto nötig | **brutto nötig** |
|---|---|---|
| bei 1,9 Trades/Tag, 1 % Risiko | +0,8701 R | **+1,0840 R** |
| bei 10 Trades/Tag, 1 % Risiko | +0,1647 R | **+0,3786 R** |

**Und hier liegt die Falle der Zeile „mehr Trades":** die Maut fällt je
*Runde* an, nicht je Zeit. Zehnmal so viele Trades senken das nötige Netto um
Faktor 5,3 — aber sie zahlen die Maut zehnmal. Das nötige **Brutto** sinkt
deshalb nur von 1,084 auf 0,379 R, nicht auf ein Fünftel.

Gemessen: die Brutto-Erwartung der genommenen Population spannt über die Null
(+0,0080 R [−0,022; +0,039]).

## 3. Was nachweisbar sein muss

Streuung je Trade **1,406 R**, Niveau 99,9091 % (Bonferroni auf 55), z = 3,317:

| echter Vorteil | Trades für ein Intervall ohne Null |
|---|---|
| **+0,7280 R** | **41** |
| +0,5000 R | 87 |
| +0,2000 R | 544 |
| +0,1000 R | 2 175 |

**Ein Vorteil, der für das Ziel reicht, ist nach 41 Trades sichtbar.** Ein
Vorteil, der nur zu +51 % über sechs Monate reicht (+0,10 R), braucht 2 175
Trades — also mehr als drei Jahre bei der gemessenen Rate.

**Daraus eine harte Folgerung:** ein Kandidat, der nach 41 homogenen
Vorwärtstrades *kein* Intervall ohne Null zeigt, ist für das Ziel kein
Kandidat — unabhängig davon, ob er einen kleinen echten Vorteil hat.

## 4. Was es *nicht* sein darf

**Kein Marktbeta.** Gemessen über 2 752 Trades: **b = +0,985**
[+0,872; +1,101] zum Kryptomarkt, Rest daneben −0,0831 R mit Intervall ohne
Null. Ein Kandidat muss ein Beta zeigen, dessen Intervall die **1
ausschliesst** — sonst ist er dasselbe System mit anderem Namen.

**Keine abgetastete Auswahl.** Von vier auf voller Abdeckung neu gemessenen
Grössen replizierten die beiden, die über das *ganze* Tape rechnen (1,00× und
1,10×); die beiden über eine abgetastete Auswahl fielen auf 0,43× und kippten
das Vorzeichen.

**Kein einzelner Markt.** Jede Zelle muss die Auslassprüfung überstehen:
jeden Markt einmal weglassen und erneut rechnen.

**Kein Hebel als Ersatz.** Der 3-%-Deckel hebt die Zielchance der gemessenen
Verteilung von 0,00 auf 0,01 % und senkt den Median von 657 auf 224 CHF.

**Keine zwölf Märkte als zwölf Beobachtungen.** Korrelierte Perps im selben
Fenster sind eine Beobachtung.

## 5. Die Checkliste

Ein Kandidat gilt erst, wenn **alle** zutreffen:

1. **Brutto** über +0,38 R je Trade (bei 10/Tag) bzw. +1,08 R (bei 1,9/Tag)
2. **Netto** positiv nach Maut, Funding, Slippage und FX
3. **Korrigiertes Intervall ohne Null** auf Niveau 0,05/n, mit aufgelöstem Rand
   (`tail_resolved`)
4. **Replikation 0,5–2,0×** zwischen zwei zeitlich getrennten Fenstern
5. **Beta-Intervall schliesst die 1 aus**
6. **Auslassprüfung** über alle Märkte bestanden
7. **Kein Look-ahead**: Zukunfts-Mutationstest grün, Features zum
   Entscheidungszeitpunkt verfügbar
8. **Vorab registriert**, mit Zellen und Abnahmekriterium, vor dem ersten Lauf
9. **Nach 41 homogenen Vorwärtstrades** sichtbar — oder es ist kein Kandidat
   für dieses Ziel
10. **Eine homogene Signatur** über alle gezählten Trades
    (`JournalEntry.run_signature`)

## 6. Und die unbequeme Lesart dieses Dokuments

Die Punkte 1 bis 10 sind nicht streng, weil jemand streng sein wollte. Sie
sind das, was die gemessenen Grössen verlangen: eine Maut von 0,21 R, eine
Streuung von 1,41 R, ein Beta von 0,985 und ein Ziel, das +0,87 R bei der
gemessenen Trade-Rate fordert.

**Ein Kandidat, der diese Hürden nicht nimmt, bringt nicht „weniger Gewinn" —
er ist von Null nicht unterscheidbar.** Das ist der Unterschied zwischen einem
Pflichtenheft und einem Wunsch.

Und die Zahl, die alles zusammenzieht: das Ziel braucht **+0,8701 R je Trade**
bei der Rate, die das System hat. Gemessen sind **−0,0906**. Das ist keine
Lücke, die ein besserer Filter schliesst.
