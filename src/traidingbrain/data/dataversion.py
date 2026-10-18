"""Welche Daten ein Lauf gelesen hat -- als Stempel, mit seiner Methode davor.

**Warum die Methode in den Wert gehört.** Es gibt hier zwei Arten,
Datenlage zu stempeln, und sie beantworten verschiedene Fragen:

* `coverage:` -- nur Fenster und Zeilenzahl je Zeitebene. Billig. **Blind
  dagegen, dass eine Quelle ihre eigene Vergangenheit umschreibt**, solange
  Fenster und Zeilenzahl gleich bleiben. Diese Blindheit ist in diesem Projekt
  gemessen worden: der Zukunfts-Mutationstest schweigt über genau diesen Fall,
  und eine Revision ist ihm unsichtbar.
* `content:` -- Hash über die Zeitstempel und Schlusskurse selbst. Fängt die
  Revision. Kostet eine Hash-Runde über die Rahmen, die beim Replay ohnehin
  im Speicher liegen.

Stünde die Methode nicht im Wert, liessen sich zwei Läufe vergleichen, von
denen einer eine Frage gestellt hat und der andere nicht. Mit ihr sind sie
verschiedene Läufe, und das ist die richtige Antwort.

**Was auch `content:` nicht leistet.** Es stempelt die Rahmen, die dieser Lauf
*gelesen* hat, nicht den Speicher. Zwei Läufe über verschiedene Symbolmengen
haben verschiedene Stempel, auch wenn der Speicher derselbe ist -- was richtig
ist, denn sie haben verschiedene Daten gesehen.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

#: Länge des Datenstempels hinter dem Methodenpräfix.
_STAMP = 12

#: Die Spalten, über die `content:` hasht.
#:
#: Zeitstempel und Schlusskurs, nicht alle fünf. Open, High und Low ändern sich
#: bei einer Revision mit, also fängt `close` die Revision ebenso -- und die
#: Hash-Runde ist halb so teuer. Die Entscheidung steht hier, damit sie beim
#: nächsten Lesen eine Entscheidung ist und keine Auslassung.
_SPALTEN = ("ts", "close")


def _fingerprint(frames: Mapping[Any, Any], *, inhalt: bool) -> str:
    teile: list[str] = []
    for key in sorted(frames, key=str):
        frame = frames[key]
        name = getattr(key, "value", str(key))
        if frame is None or frame.empty:
            teile.append(f"{name}=leer")
            continue
        if inhalt:
            roh = b"".join(
                frame[spalte].to_numpy().tobytes()
                for spalte in _SPALTEN
                if spalte in frame.columns
            )
            teile.append(f"{name}={hashlib.sha256(roh).hexdigest()}")
        else:
            teile.append(
                f"{name}={int(frame['ts'].iloc[0])}-{int(frame['ts'].iloc[-1])}"
                f"x{len(frame)}"
            )
    joined = "\x00".join(teile)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:_STAMP]


def content_version(frames: Mapping[Any, Any]) -> str:
    """Ein Stempel über die gelesenen Werte selbst. Fängt eine Revision."""
    return f"content:{_fingerprint(frames, inhalt=True)}"


def coverage_version(frames: Mapping[Any, Any]) -> str:
    """Ein Stempel über Fenster und Zeilenzahl. Billig, und blind für Revisionen."""
    return f"coverage:{_fingerprint(frames, inhalt=False)}"
