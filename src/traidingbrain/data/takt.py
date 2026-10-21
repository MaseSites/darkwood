"""Balken nach Volumen oder Umsatz statt nach der Uhr -- der Takt fuer E24.

Jede Messung dieses Projekts liegt auf Zeitbalken: `Timeframe` ist ein
`StrEnum` aus Minuten, und `timeframe_ms` ist der ganze Gitterbegriff. Der
Blindfleck-Audit vom 18.10.2026 nannte den Takt der Balken als einzigen
Kandidaten, den keine Arithmetik unter die Zielmarke begrenzt, weil er die
EINSTIEGSPOPULATION austauscht statt sie auszuwaehlen. E24 im Register prueft
ihn -- als Falsifikation, mit der Erwartung "unentschieden".

**Was ein Takt-Balken ist.** Aus den Minutenkerzen wird fortlaufend Volumen
(oder Umsatz, `close * volume`) aufsummiert. Sobald die Summe eine Schwelle
ueberschreitet, schliesst der Balken mit DIESER Minute; die naechste Minute
oeffnet den naechsten. Ein Balken dauert also eine Minute in einer Panik und
Stunden in der Nacht. Das ist der Punkt: die Detektoren sehen gleich viel
Handel je Balken statt gleich viel Zeit.

**Die Hierarchie.** Die Setups feuern auf benannten Ebenen (M15, H1, H4, D1,
W1), und die Konfiguration verlangt genau diese Namen. Darum tragen die
Takt-Balken dieselben Namen und stehen im Verhaeltnis der Zeitebenen
zueinander: die M15-Schwelle ist die Basis, H1 das Vierfache, H4 das
Sechzehnfache, D1 das 96-fache, W1 das 672-fache. Dieselben Detektoren,
dieselben Konstanten, nur der Balkenbegriff wechselt -- das verlangt die
Abgrenzung im Register.

**Was anders gespeichert wird.** Ein Zeitbalken kennt seine Schlusszeit aus
seiner Oeffnung: `ts + timeframe_ms`. Ein Takt-Balken nicht. Darum traegt jeder
Takt-Balken eine Spalte `close_ts` (Schlusszeit der letzten Minute plus eine
Minute), und Pipeline, Motor und Journal lesen sie, wenn sie da ist. Fehlt die
Spalte, rechnen sie wie bisher; das haelt jeden Zeitbalken-Lauf byte-gleich,
und `tests/test_backtest.py` friert das ein.

**Die Schwelle.** Je Markt der MITTELWERT des M15-Volumens ueber die ganze
Historie (nicht der Median: der liegt bei schiefem Volumen so tief, dass
1,85-mal so viele Balken entstehen wie M15-Kerzen, gemessen an BTC und ADA am
21.10.2026). Mit dem Mittelwert entspricht die Balkenzahl der M15-Zahl, und
die Vergleichbarkeit der Kadenz ist das, was die Tore brauchen. Fest ueber die
Historie, nicht gleitend: das ist die kanonische Definition, und sie heisst,
dass ein Jahr mit viel Handel mehr Balken bekommt. Genau das soll der Takt tun.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from traidingbrain.domain.enums import Timeframe

#: Schwellenfaktor je benannter Ebene, im Verhaeltnis der Minuten.
HIERARCHIE: dict[Timeframe, int] = {
    Timeframe.M15: 1,
    Timeframe.H1: 4,
    Timeframe.H4: 16,
    Timeframe.D1: 96,
    Timeframe.W1: 672,
}

#: Spalten eines Takt-Rahmens: OHLCV wie ueberall, dazu die Schlusszeit und
#: die Zahl der Minuten, aus denen der Balken besteht.
TAKT_COLUMNS = ("ts", "open", "high", "low", "close", "volume", "close_ts", "minutes")

MINUTE_MS = 60_000


@dataclass(frozen=True)
class Takt:
    """Welche Groesse zaehlt, und wie die Schwelle je Markt entsteht."""

    name: str  # "volumen" oder "dollar"

    def groesse(self, frame: pd.DataFrame) -> np.ndarray:
        volume = frame["volume"].to_numpy(dtype="float64")
        if self.name == "volumen":
            return volume
        if self.name == "dollar":
            return frame["close"].to_numpy(dtype="float64") * volume
        raise ValueError(f"unbekannter Takt: {self.name!r}")

    def basis_schwelle(self, m15: pd.DataFrame) -> float:
        """Mittelwert der M15-Groesse: so viele Balken wie M15-Kerzen."""
        if m15.empty:
            raise ValueError("keine M15-Kerzen, aus denen eine Schwelle entstehen koennte")
        return float(self.groesse(m15).mean())


VOLUMEN = Takt("volumen")
DOLLAR = Takt("dollar")
ARME: dict[str, Takt] = {"volumen": VOLUMEN, "dollar": DOLLAR}


def takt_balken(m1: pd.DataFrame, groesse: np.ndarray, schwelle: float) -> pd.DataFrame:
    """Minuten zu Balken buendeln, sobald die laufende Summe die Schwelle reisst.

    Vektorisiert ueber die kumulierte Summe: Minute i gehoert zu Balken
    floor(S_{i-1} / schwelle), wobei S_{i-1} die Summe VOR der Minute ist. Die
    Minute, die eine Grenze ueberschreitet, schliesst damit den Balken, den sie
    vollendet; ihr Ueberschuss zaehlt fuer den naechsten mit. Ein Balken traegt
    daher mindestens die Schwelle, im Mittel genau die Schwelle. Der letzte,
    unvollstaendige Balken wird verworfen -- wie `drop_forming` bei Zeitbalken.
    """
    if m1.empty or schwelle <= 0:
        return leerer_takt_rahmen()
    ts = m1["ts"].to_numpy(dtype="int64")
    if np.any(np.diff(ts) <= 0):
        raise ValueError("Minuten muessen streng aufsteigend und eindeutig sein")
    opens = m1["open"].to_numpy(dtype="float64")
    highs = m1["high"].to_numpy(dtype="float64")
    lows = m1["low"].to_numpy(dtype="float64")
    closes = m1["close"].to_numpy(dtype="float64")
    volume = m1["volume"].to_numpy(dtype="float64")

    summe = np.cumsum(groesse)
    vorher = summe - groesse
    bar_id = np.floor(vorher / schwelle).astype("int64")
    # Grenzen: erster Index jedes Balkens.
    start = np.flatnonzero(np.r_[True, bar_id[1:] != bar_id[:-1]])
    ende = np.r_[start[1:], ts.size]  # exklusiv
    # `reduceat` rechnet das letzte Segment immer bis zum Ende des Arrays, also
    # werden die Aggregate ueber ALLE Starts gebildet und der unfertige Rest
    # erst danach verworfen -- sonst traegt der letzte fertige Balken die
    # Minuten des Rests mit (so gefunden von tests/test_takt.py).
    hoch = np.maximum.reduceat(highs, start)
    tief = np.minimum.reduceat(lows, start)
    vol = np.add.reduceat(volume, start)
    # Der letzte Balken ist nur fertig, wenn seine Summe die naechste Grenze reisst.
    letzte_grenze = (bar_id[start[-1]] + 1) * schwelle
    if summe[-1] < letzte_grenze:
        start, ende = start[:-1], ende[:-1]
        hoch, tief, vol = hoch[:-1], tief[:-1], vol[:-1]
    if start.size == 0:
        return leerer_takt_rahmen()

    out = pd.DataFrame(
        {
            "ts": ts[start],
            "open": opens[start],
            "high": hoch,
            "low": tief,
            "close": closes[ende - 1],
            "volume": vol,
            "close_ts": ts[ende - 1] + MINUTE_MS,
            "minutes": (ende - start).astype("int64"),
        }
    )
    return out.astype({"ts": "int64", "close_ts": "int64", "minutes": "int64"})


def leerer_takt_rahmen() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.Series(dtype="int64"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
            "close_ts": pd.Series(dtype="int64"),
            "minutes": pd.Series(dtype="int64"),
        }
    )


def takt_hierarchie(
    m1: pd.DataFrame, takt: Takt, basis_schwelle: float
) -> dict[Timeframe, pd.DataFrame]:
    """Alle fuenf benannten Ebenen aus denselben Minuten, je mit ihrer Schwelle."""
    groesse = takt.groesse(m1)
    return {
        tf: takt_balken(m1, groesse, basis_schwelle * faktor)
        for tf, faktor in HIERARCHIE.items()
    }


def has_close_ts(frame: pd.DataFrame) -> bool:
    return "close_ts" in frame.columns


def schreibe(frames: dict[Timeframe, pd.DataFrame], ordner: Path) -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    for tf, frame in frames.items():
        frame.to_parquet(ordner / f"{tf.value}.parquet", index=False)


def lese(ordner: Path, timeframes: list[Timeframe]) -> dict[Timeframe, pd.DataFrame]:
    return {tf: pd.read_parquet(ordner / f"{tf.value}.parquet") for tf in timeframes}
