# Gewinner gegen Verlierer — was die Gewinner gemeinsam hatten, 21.10.2026

Auftrag des Eigentümers, wörtlich: *„analysiere alle gewonnenen Trades, was
hast du dort anders gemacht als bei den verlorenen, egal was es ist, MACHE ES
WIEDER."* Dazu: keine neuen Trades, bis das umgesetzt ist.

Stand bei Auftrag: Plankonto **26 Trades, −9,34 R, −174,92 USD**; über alle
Konten 59 Live-Trades, 39 % Treffer, −0,064 R je Trade. Kill-Switch gesetzt
um 11:10 UTC; offene Positionen werden weiter geführt.

## Methode

Jeder Live-Trade trägt seinen Entscheidungsblock. Gewinner und Verlierer
wurden über **jedes** Vor-Trade-Merkmal geschnitten: Setup, Ebene, Seite,
Regime, Rating, Widerspruch der Familien, Richtung gegen Gesamtbild,
Stopweite, Kostenanteil, Tageszeit, Markt. Dann die Falle, in die dieses
Projekt schon zweimal gelaufen ist: 59 Trades erzählen immer eine Geschichte.
Darum wurde **jede** Differenz gegen zwei unabhängige Populationen gehalten:

* das Replay, 7'335 Trades auf den zwölf gehandelten Märkten;
* die 56 **ungesehenen** Märkte aus E17, 39'075 Trades, Entscheidungsblock
  dabei.

Eine Differenz zählt nur, wenn sie in allen drei dieselbe Richtung zeigt.

## Das Ergebnis

| Merkmal | live (59) | Replay (7'335) | ungesehen (39'075) | Urteil |
|---|---|---|---|---|
| **M15-Setup** gegen H1 und höher | 33 % / −0,27 R gegen 48 % / +0,25 R | 35 % / −0,037 gegen 38–40 % / +0,01 bis +0,04 | 34,6 % / −0,064 gegen 37,9 % / +0,001 | **hält dreifach** |
| **gegen das Gesamtbild** gegen mit | 28 % / −0,38 R gegen 44 % / +0,07 R | 32 % / −0,054 gegen 38 % / −0,002 | 32,4 % / −0,072 gegen 37,4 % / −0,019 | **hält dreifach** |
| teuer (Kosten > 8 % des Risikos) | 30 % / −0,47 R gegen 44 % / +0,15 R | Replay lief mit Deckel; 43'727 Signale: teuer −0,21 R netto | — | hält, Deckel seit heute Morgen wieder zu |
| Widerspruch der Familien > 50 % | 11 % / −0,73 R | 36 % / −0,017 gegen −0,012 | 35,7 % / −0,034 gegen −0,030 | **Rauschen** |
| Rating hoch / mittel / tief | 39 / 44 / 22 % | 38 / 35 / 37 % | 36,8 / 35,7 / 35,8 % | **Rauschen** |
| Short im Aufwärtstrend | 2 von 10 | −0,052 R, n=627 | — | Rauschen |
| Setup B gut, G schlecht | +0,29 / −0,59 R | −0,011 / +0,041 | −0,029 / −0,005 | Rauschen |
| 00–08 UTC | 1 von 12 | −0,024 / +0,014 | — | Rauschen |
| Markt (SOL, BTC schlecht) | 2 von 9, 1 von 5 | +0,031 / −0,035 | — | Rauschen |

**Beide Merkmale zusammen, ungesehen:** H1 und höher **und** mit dem Bild:
**38,9 % Treffer, +0,0024 R, n=17'213.** Gegen M15 und gegen das Bild:
32,4 %, −0,110 R.

## Was umgesetzt ist

Zwei Regeln, beide als Konfiguration in `config_offen/settings.yaml`, beide
in der Laufsignatur (`|tf=D1,H4,H1|bild`), beide rückgängig durch Löschen
zweier Zeilen:

1. **`setups.timeframes: [D1, H4, H1]`** — der Pool durchsucht M15 nicht
   mehr. `GuidePool.timeframes`, `allowed_timeframes(config)`, und die
   Journal-Zuordnung `_setup_for` sucht nur noch auf diesen Ebenen (sonst
   bekäme ein H1-Trade das Etikett M15, wenn beide feuerten — derselbe
   Fehler wie bei Setup C).
2. **`setups.require_agreement: true`** — ein Setup, dessen Seite dem
   `score_direction` widerspricht, wird im Live-Pfad vor `assess` abgelehnt
   und als Signal mit `Rule.PICTURE` („bild") festgehalten. Bis heute stand
   in `journal/record.py` wörtlich, dass nichts in den Einstiegsregeln darauf
   achtet.

Dazu seit heute Morgen: Kostentor wieder 0,08, höchstens zwei Positionen je
Richtung.

## Was das ist — und was nicht

Es ist **das Weglassen der gemessen schlechtesten Population**, dreifach
bestätigt. Es ist **kein Vorteil**: die beste Zelle liegt out-of-sample bei
**+0,002 R** mit **39 % Treffern**. Das heisst Break-even, nicht „Trades
gewinnen". Rund die Hälfte der bisherigen Trades fällt weg (M15 war 48 % der
Trades, „gegen das Bild" 22 %); mit dem Kostentor noch mehr. Wer erwartet,
dass die Stops jetzt aufhören, wird enttäuscht: bei 39 % Treffern landen
sechs von zehn Trades weiterhin im Stop. Was sich ändern sollte, ist die
**Summe**, nicht das Gefühl je Trade.

Vorregistriert als Vorwärtstest (Register E27): diese Epoche wird gegen die
vorige am Mittel in R und an der Trefferquote gemessen, frühestens bei 100
Trades; Tor: Mittel der neuen Epoche ≥ 0 mit Intervall. Keine weitere
Anpassung an die laufende Stichprobe, bis das vorliegt.

## Nachrechnen

```
python - <<'EOF'
# Live-, Replay- und E17-Schnitte wie oben: scripts/study_edge.py --source live
EOF
```
`scripts/study_edge.py` liefert die Schnitte mit Bonferroni; die Tabelle oben
entstand aus denselben Feldern (`reason.setup_timeframe`, `reason.side`,
`reason.score_direction`) über `data/journal.sqlite`, `data/replay_fills/`
und `data/replay_fills_0311/`.
