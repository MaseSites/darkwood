"""Zwei Ebenen zur Entscheidungszeit aufzeichnen -- Kalender- und Strike-Abstand.

**Warum es dieses Modul gibt.** Der Eigentuemer verlangte am 21.10.2026, dass
das System "alle Terminal-Ebenen anschaut". Von dreizehn Ebenen sind fuenf die
Setups selbst und sechs stammen aus Datenfamilien, die am 14.10. als
Praediktoren geschlossen wurden (Register, `geschlossene_datenfamilien`). Zwei
Einzelgroessen sind nie als solche geprueft worden: der Abstand zum naechsten
Kalendertermin (E12 prueft nur Wochenende und Funding-Stunde) und der Abstand
zum naechsten grossen Options-Strike (GEX hat kein belegbares Vorzeichen; der
reine Abstand wurde nie gemessen). Beide haben keine Historie, also sind sie
nur VORWAERTS messbar: hier zur Entscheidungszeit aufschreiben, Wochen
sammeln, dann als E26 gegen die Schranke des Registers pruefen.

**Was dieses Modul NICHT tut.** Es schaltet nichts. Kein Einstieg liest diese
Tabelle, und das bleibt so, bis eine vorregistrierte Messung ein Intervall
ohne Null zeigt. Ein Aufzeichner, der nebenbei filtert, waere genau die Sorte
"Ebene", vor der das Projekt sich mit dem Register schuetzt.

**Die Definitionen, vorab und fest**, damit eine spaetere Auswertung nicht
nachtraeglich die guenstigste waehlt:

* Kalender: Minuten bis zum naechsten Termin je Impact-Stufe (`high`,
  `medium`), nur Termine, die zur Entscheidungszeit schon bekannt waren
  (`is_knowable_at`), Horizont 7 Tage. Kein Termin im Horizont: NULL.
* Strike: "gross" heisst mindestens ein Viertel des groessten offenen
  Interesses ueber alle Strikes (Calls + Puts). Der naechste grosse Strike ist
  der mit dem kleinsten Abstand zum Spot in Prozent, vorzeichenbehaftet
  (positiv: Strike ueber Spot). Dazu getrennt der Strike mit dem groessten
  offenen Interesse. Das Viertel ist eine Setzung; es steht hier, damit es
  eine Setzung bleibt und keine Suche wird.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from traidingbrain.data.calendar import MacroCalendar

#: Entscheidungstakt des Haendlers.
M15_MS = 15 * 60_000
#: Wie weit der Kalender vorausschaut.
KALENDER_HORIZONT_H = 7 * 24
#: Ab welchem Anteil des groessten offenen Interesses ein Strike "gross" ist.
GROSS_ANTEIL = 0.25

SCHEMA = """
CREATE TABLE IF NOT EXISTS ebenen (
    ts                      INTEGER NOT NULL,
    symbol                  TEXT    NOT NULL,
    preis                   REAL,
    kalender_min_high       INTEGER,
    kalender_min_medium     INTEGER,
    kalender_name           TEXT,
    strike_naechst          REAL,
    strike_abstand_pct      REAL,
    strike_oi               REAL,
    strike_max              REAL,
    strike_max_abstand_pct  REAL,
    strike_max_oi           REAL,
    quelle                  TEXT,
    geschrieben_utc         TEXT    NOT NULL,
    PRIMARY KEY (ts, symbol)
)
"""


def entscheidungszeit(now_ms: int) -> int:
    """Die zuletzt geschlossene M15-Grenze -- der Balken, auf dem entschieden wird."""
    return (now_ms // M15_MS) * M15_MS


@dataclass(frozen=True)
class KalenderAbstand:
    min_high: int | None
    min_medium: int | None
    name: str | None


def kalender_abstand(kalender: MacroCalendar, now_ms: int) -> KalenderAbstand:
    """Minuten bis zum naechsten bekannten Termin je Stufe, oder None."""
    kommend = kalender.upcoming(now_ms, horizon_hours=KALENDER_HORIZONT_H)
    high = [e for e in kommend if e.impact == "high"]
    medium = [e for e in kommend if e.impact == "medium"]
    naechster = kommend[0] if kommend else None
    return KalenderAbstand(
        min_high=high[0].minutes_until(now_ms) if high else None,
        min_medium=medium[0].minutes_until(now_ms) if medium else None,
        name=naechster.name if naechster else None,
    )


@dataclass(frozen=True)
class StrikeAbstand:
    naechst: float | None
    abstand_pct: float | None
    oi: float | None
    max_strike: float | None
    max_abstand_pct: float | None
    max_oi: float | None


def strike_abstand(spot: float, strikes: list[tuple[float, float]]) -> StrikeAbstand:
    """Naechster grosser Strike und groesster Strike, je mit Abstand zum Spot.

    `strikes` sind Paare (Strike, offenes Interesse Calls + Puts).
    """
    leer = StrikeAbstand(None, None, None, None, None, None)
    if spot <= 0 or not strikes:
        return leer
    mit_oi = [(k, oi) for k, oi in strikes if oi > 0]
    if not mit_oi:
        return leer
    max_strike, max_oi = max(mit_oi, key=lambda p: p[1])
    grosse = [(k, oi) for k, oi in mit_oi if oi >= GROSS_ANTEIL * max_oi]
    naechst, oi = min(grosse, key=lambda p: abs(p[0] - spot))

    def pct(k: float) -> float:
        return round((k - spot) / spot * 100.0, 4)

    return StrikeAbstand(
        naechst=naechst, abstand_pct=pct(naechst), oi=round(oi, 1),
        max_strike=max_strike, max_abstand_pct=pct(max_strike), max_oi=round(max_oi, 1),
    )


def oeffne(pfad: Path) -> sqlite3.Connection:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(pfad)
    con.execute(SCHEMA)
    return con


def schreibe(con: sqlite3.Connection, zeile: dict) -> bool:
    """Eine Zeile je (ts, symbol); ein Doppelstart ueberschreibt nicht."""
    spalten = ", ".join(zeile)
    platz = ", ".join("?" for _ in zeile)
    cur = con.execute(
        f"INSERT OR IGNORE INTO ebenen ({spalten}) VALUES ({platz})", list(zeile.values())
    )
    con.commit()
    return cur.rowcount == 1
