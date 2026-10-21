# E22 — Der Rückgabe-Trail ist gefallen

Gelaufen am 21.10.2026, Vorregistrierung vom 20.10. in
`audit/E22_TRAIL_VORREGISTRIERUNG.md`. Nachrechnen: `python scripts/study_exits.py`

## Das Ergebnis

858 Fälle, gepaart — jeder Arm sieht dieselben Einstiege.

| Arm | Netto-R | Haltezeit | gepaarte Differenz zur Basis |
|---|---|---|---|
| **E3.1 Stop und Ziel (Basis)** | −0.0309 | 12.4 h | — |
| E22 Rückgabe-Trail 0.25 R | −0.0502 | 0.4 h | −0.0193 [−0.1770, +0.1305] |
| E22 Rückgabe-Trail 0.50 R | −0.0866 | 1.8 h | −0.0557 [−0.2080, +0.0856] |
| E22 Rückgabe-Trail 0.75 R | −0.0902 | 4.1 h | −0.0593 [−0.1922, +0.0699] |
| E22 Rückgabe-Trail 1.00 R | −0.0916 | 7.1 h | −0.0607 [−0.1924, +0.0561] |

**Alle vier Zellen sind schlechter als die Basis, und monoton schlechter mit
wachsendem G.** Die Tore:

```
(a) gepaarter Mehrwert mit korrigiertem Intervall ohne Null:  KEINER
(b) absolut netto positiv:                                     KEINER
->  NICHT BELEGT
```

## Die Vorregistrierung hat ihren eigenen Ausgang vorhergesagt

Abschnitt 7 lautete: *„Wenn der Trail die Gewinner köpft… E3.3 ist genau daran
gescheitert (Trail greift in 99 %)."*

Genau das ist eingetreten:

```
E3.1 Basis                  stop 57.9%   zeit 10.5%   ziel 31.6%
E22 Rückgabe-Trail 0.25 R   trail 99.9%  zeit  0.1%   ziel  0%
E22 Rückgabe-Trail 1.00 R   trail 95.7%  zeit  4.3%   ziel  0%
```

Die Basis erreicht in **31.6 %** der Fälle ihr Ziel. Unter jedem Trail-Arm
sind es **null**. Der Trail greift vorher — immer. Die Auszahlung ist fest
(Gewinner ~+1.48 R, Verlierer −1.05 R); wer die Gewinner bei einem Bruchteil
davon abschneidet, verliert mehr als er an den Verlierern rettet.

## Was dieses Ergebnis NICHT trägt

> [!warning] Alle 858 Fälle stammen aus EINEM Markt.
> Unter dieser Signatur hat nur ADAUSDT genug aufgelöste Signale (4'458 → 858).
> Die übrigen elf Märkte tragen zusammen **null** Fälle bei. Das ist kein
> Querschnitt über zwölf Märkte, sondern eine Messung auf einem — und
> gemessen trägt ein gemeinsamer Wochenfaktor ohnehin 96.9 % der Struktur.

Dazu, wie die Vorregistrierung selbst festhält: diese Signale haben **nie um
einen Platz konkurriert**. Ein längerer Halt belegt Slots, die ein anderer
Trade gebraucht hätte. Das sieht nur ein vollständiger Portfolio-Replay.

## Ein Fehler, der beim Lauf aufgefallen ist

`study_exits.py` rechnete mit **46** angemeldeten Vergleichen, während
`audit/EXPERIMENTS_NEXT.yaml` **73** führte. Eine zu kleine Zahl macht die
Bonferroni-Schwelle zu **mild** — 0.05/46 statt 0.05/73 — und das ist die
gefährliche Richtung: ein Befund wird leichter, nicht schwerer.

**Dass es diesen Lauf nicht entwertet, ist Glück und kein Argument:** es
bestand kein Arm, und eine strengere Schwelle hätte daran nichts geändert.
Wäre einer knapp durchgekommen, stünde hier eine zurückgenommene Aussage.

Behoben: das Werkzeug liest die Zahl jetzt aus dem Register, statt eine zweite
zu halten. Register auf **77** (73 + die vier E22-Zellen). Das Ergebnis oben
ist mit 77 gerechnet, Niveau 99.935 %.

## Abweichung von der Vorregistrierung, offen benannt

Vorgesehen war ein neues Simulatorfeld `trail_giveback_r` in `sim/broker.py`.
Gebaut ist der Arm im Replay-Werkzeug `scripts/study_exits.py`. Zwei Gründe,
beide inhaltlich:

1. **Dieselbe Population und derselbe Fill wie E3.1–E3.3** — die Arme sind
   damit direkt vergleichbar, was bei einer Änderung am Broker nicht
   selbstverständlich gewesen wäre.
2. **Der Entscheidungspfad bleibt unberührt**, die laufende
   Vorwärtsstichprobe wird nicht unterbrochen.

Die gemessene Grösse ist dieselbe: der Stop folgt dem günstigsten erreichten
Punkt im Abstand `G × risk_price` und wird nie zurückgenommen.

## Einordnung

Das ist der **siebte** gefallene Ausstiegsarm. E3.1/3.2/3.3, E10
(schlusskursbestätigter Stop), E14 und E15 (Breakeven-Stop, monoton
schlechter), jetzt E22 in vier Zellen.

Die Ausstiegsachse ist damit nicht formal erschöpft — aber sieben Versuche mit
sieben Fehlschlägen, davon zwei mit monotoner Verschlechterung, sind ein
Muster und kein Zufall. **Das Rückgabe-Problem ist kein Ausstiegsproblem.**
