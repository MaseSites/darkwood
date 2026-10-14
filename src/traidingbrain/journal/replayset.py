"""Die Replay-Population mit ihrer Herkunft — statt der, die keine hat.

**Der Anlass, 14.10.2026 — und er ist eine Wiederholung, keine Entdeckung.**
Die Journal-Datenbank hält 2.734 Zeilen mit `source=REPLAY`, und über sie war
den ganzen Tag berichtet worden. Nachgesehen:

* Sie decken **vier** Märkte (BTC, ETH, SOL, XRP), nicht zwölf.
* `run_signature`, `decision_version` und `code_version` sind bei allen 2.734
  **leer**.
* Und sie stimmen nicht einmal mit den vier gleichnamigen Märkten in
  `data/replay_fills/` überein: dort hat BTCUSDT 263 Trades, in der Datenbank
  495. Es ist ein anderer, älterer Lauf.

Damit ist die Population **nicht identifizierbar**. Welche Konfiguration und
welcher Codestand sie erzeugt haben, ist aus den Daten nicht zu beantworten —
genau die Frage, für die `run_signature` und `decision_version` gebaut wurden.

Und der Unterschied ist nicht klein. Über zwölf Märkte statt vier:

                              vier (Datenbank)   zwölf (Dateien)
    beste Lage je Trade            +1.4964 R        +1.1840 R
    Ergebnis je Trade              -0.0906 R        -0.0129 R
    Rueckgabe                      +1.5871 R        +1.1969 R
    Ziel nie erreicht                 67.8 %           62.9 %
    nie im Plus                        7.0 %           14.5 %

Die Richtung jedes Befunds hält. Die Grössen nicht: „nie im Plus" verdoppelt
sich, und das Ergebnis je Trade wird siebenmal kleiner. Vier Märkte als „das
System" zu zitieren ist derselbe Fehler, den dieses Projekt schon einmal
bezahlt hat — die alten BTC-Zahlen setzten den Nullpunkt in Reichweite eines
3-%-Gebührenrabatts, wo vier Märkte ihn bei 69 % fanden.

**Und das alles stand schon da.** `scripts/eval_replay_rerun.py` beschreibt
es seit dem 11.10.2026 im eigenen Docstring, mit derselben Zahl: „Das
Journal hält den *alten* Lauf; der Neulauf schrieb nichts hinein“, BTCUSDT
495 gegen 263. Dort steht es als einer von zwei Fehlversuchen EINER
Auswertung — und drei Tage später bin ich in dieselbe Grube gelaufen, in
jeder Replay-Zahl des Tages.

Daraus folgt, was hier neu ist, und es ist nicht der Befund: ein Hinweis im
Docstring eines Skripts schützt nur dieses Skript. `scripts/goal.py` hatte
denselben Defekt, unbemerkt, in dem Bericht, der die Zielfrage beantwortet.

**Was dieses Modul deshalb tut:** es liest die Population aus den
Replay-Dateien, die ihre Herkunft je Datei UND je Eintrag tragen, und es
nennt sie. Ein Bericht, der nicht sagt, über welche Märkte und welchen
Codestand er rechnet, ist nicht lesbar — und wer die Menge über diese
Funktion holt, bekommt die Herkunft mitgeliefert, statt sie zu kennen zu
müssen.

Nicht importiert vom Live-Entscheidungspfad und darum ausserhalb des
Abschlusses — eine Änderung hier bewegt den Entscheidungsstempel nicht.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReplaySet:
    """Replay-Trades, und woher sie kommen."""

    entries: list[dict]
    markets: tuple[str, ...]
    stamps: tuple[str, ...]
    signatures: tuple[str, ...]

    @property
    def mixed(self) -> bool:
        """Ob mehr als ein Codestand oder mehr als eine Konfiguration drin ist.

        Keine Ausnahme, sondern eine Eigenschaft, die der Aufrufer berichten
        muss. Eine gemischte Menge ist manchmal die einzige, die es gibt --
        aber sie darf nicht aussehen wie eine saubere.
        """
        return len(self.stamps) > 1 or len(self.signatures) > 1

    def labelled(self) -> str:
        """Die Zeile, die in jeden Bericht gehört, der diese Menge benutzt."""
        head = (
            f"{len(self.entries):,} Replay-Trades aus {len(self.markets)} Maerkten"
        )
        if self.mixed:
            return (
                f"{head}  !! GEMISCHT: {len(self.stamps)} Codestaende, "
                f"{len(self.signatures)} Konfigurationen -- die Zahlen "
                "gehoeren nicht zu einem Lauf"
            )
        return f"{head}, Stand {self.stamps[0]}"


def load_replay(data_dir: Path) -> ReplaySet | None:
    """Jeden Replay-Trade aus `data/replay_fills/`, mit Herkunft.

    `None`, wenn keine Datei da ist. Ausdrücklich nicht „eine leere Menge":
    eine Auswertung über null Trades druckt sonst ein zuversichtliches Nichts,
    und das ist in diesem Projekt schon zweimal passiert.

    Gelesen wird die `journal`-Liste und nicht `fills`: nur sie trägt
    `post_mortem`, also die beste und die schlimmste Lage, aus denen der
    Rückgabe-Befund besteht.
    """
    folder = data_dir / "replay_fills"
    if not folder.is_dir():
        return None

    entries: list[dict] = []
    markets: list[str] = []
    stamps: set[str] = set()
    signatures: set[str] = set()

    for path in sorted(folder.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        rows = blob.get("journal") or []
        if not rows:
            continue
        entries.extend(rows)
        markets.append(blob.get("symbol", path.stem))
        stamps.add(blob.get("decision_version", "?"))
        signatures.add(blob.get("run_signature", "?"))

    if not entries:
        return None
    return ReplaySet(
        entries=entries,
        markets=tuple(markets),
        stamps=tuple(sorted(stamps)),
        signatures=tuple(sorted(signatures)),
    )
