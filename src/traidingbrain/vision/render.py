"""Kerzen als PNG, damit ein Modell den Chart sieht und nicht nur Zahlen.

Das Bild enthaelt keine Information, die nicht auch in den Kerzen steht. Es ist
eine andere DARSTELLUNG derselben Daten, und ob sie einem Modell mehr verraet,
ist eine offene Frage, die der Schattenbetrieb messen soll -- nicht eine
Annahme, auf der irgendetwas handelt.

Zwei Regeln:

**Keine Kerze nach der Entscheidung.** Wer ein Bild zeichnet, das ueber den
Entscheidungszeitpunkt hinausreicht, zeigt dem Modell die Antwort. Der Aufrufer
schneidet ab (`bis_ms`), und dieses Modul vertraut dem nicht blind: es schneidet
selbst noch einmal.

**Gezeichnet mit Pillow, nicht im Browser.** Der Haendler laeuft ohne Oberflaeche
und muss das Bild selbst erzeugen koennen; derselbe Zeichner dient dem Chat, damit
beide Bots dasselbe Bild sehen.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

#: Breite des Bildes. Breit genug, dass 120 Kerzen je ~9 px bekommen; klein genug,
#: dass das Bild unter der Kantenlaenge bleibt, ab der Claude herunterskaliert.
BREITE = 1400

#: Hoehe eines Panels (Kurs plus Volumen).
PANEL_HOEHE = 420

#: So viele Kerzen je Panel, wenn der Aufrufer nichts sagt.
KERZEN = 120

_RAND_LINKS = 12
_RAND_RECHTS = 170
_KOPF = 34
_VOLUMEN = 64
_FUSS = 24

# Die Farben des Terminals (dunkles Blau-Schwarz, keine Schatten).
_HINTERGRUND = "#060910"
_GITTER = "#131a26"
_TEXT = "#9aa4b2"
_TITEL = "#e6ebf2"
_AUF = "#26a69a"
_AB = "#ef5350"

#: Farbe je Linienrolle; unbekannte Rollen sind grau.
ROLLENFARBE: dict[str, str] = {
    "entry": "#4aa3ff",
    "stop": "#ef5350",
    "target": "#26a69a",
    "liquidation": "#ff9f43",
    "level": "#7d8590",
}


@dataclass(frozen=True)
class Linie:
    """Eine waagerechte Linie mit Beschriftung."""

    preis: float
    text: str
    rolle: str = "level"


@dataclass
class Panel:
    """Ein Zeitrahmen: Kerzen und die Linien darueber."""

    titel: str
    kerzen: pd.DataFrame
    linien: list[Linie] = field(default_factory=list)


def _schrift(groesse: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=groesse)
    except (TypeError, OSError):  # Pillow ohne FreeType
        return ImageFont.load_default()


def nur_bis(
    frame: pd.DataFrame, bis_ms: int, *, bar_ms: int, kerzen: int = KERZEN
) -> pd.DataFrame:
    """Die letzten `kerzen` Kerzen, die bis `bis_ms` GESCHLOSSEN waren.

    Am Schluss gemessen, nicht am Beginn: eine H4-Kerze, die vor der Entscheidung
    begann und danach schloss, traegt Hoch und Tief aus der Zukunft. Liest der
    Schatten erst nach einem Neustart, liegt sie inzwischen fertig im Speicher.
    """
    geschlossen = frame["ts"] + bar_ms <= bis_ms
    return frame.loc[geschlossen].tail(kerzen).reset_index(drop=True)


def preisformat(preis: float) -> str:
    """Stellen nach der Groessenordnung: 67'412 und 0.5123 lesen sich beide."""
    if preis == 0 or not math.isfinite(preis):
        return f"{preis:g}"
    stellen = max(0, 4 - int(math.floor(math.log10(abs(preis)))))
    return f"{preis:,.{min(stellen, 8)}f}"


def _runde_schritte(tief: float, hoch: float, anzahl: int = 6) -> list[float]:
    spanne = hoch - tief
    if spanne <= 0:
        return [tief]
    roh = spanne / anzahl
    basis = 10 ** math.floor(math.log10(roh))
    schritt = next(f * basis for f in (1, 2, 2.5, 5, 10) if f * basis >= roh)
    start = math.ceil(tief / schritt) * schritt
    return [start + i * schritt for i in range(int((hoch - start) / schritt) + 1)]


def _bereich(kerzen: pd.DataFrame, linien: Sequence[Linie]) -> tuple[float, float]:
    """Kursbereich: alle Kerzen plus Plan-Linien; Levels nur, wenn sie nah genug liegen."""
    tief, hoch = float(kerzen["low"].min()), float(kerzen["high"].max())
    spanne = max(hoch - tief, abs(hoch) * 1e-4)
    for linie in linien:
        nah = tief - spanne * 0.5 <= linie.preis <= hoch + spanne * 0.5
        if linie.rolle in ("entry", "stop", "target") or nah:
            tief, hoch = min(tief, linie.preis), max(hoch, linie.preis)
    rand = (hoch - tief) * 0.05 or abs(hoch) * 0.01
    return tief - rand, hoch + rand


def _gestrichelt(d: ImageDraw.ImageDraw, x0: int, x1: int, y: float, farbe: str) -> None:
    for x in range(x0, x1, 10):
        d.line([(x, y), (min(x + 6, x1), y)], fill=farbe, width=1)


def _zeichne_panel(d: ImageDraw.ImageDraw, panel: Panel, oben: int) -> None:
    kerzen = panel.kerzen
    links, rechts = _RAND_LINKS, BREITE - _RAND_RECHTS
    kurs_oben = oben + _KOPF
    kurs_unten = oben + PANEL_HOEHE - _VOLUMEN - _FUSS
    vol_oben, vol_unten = kurs_unten + 6, oben + PANEL_HOEHE - _FUSS

    d.text((links, oben + 8), panel.titel, fill=_TITEL, font=_schrift(16))
    if kerzen.empty:
        d.text((links, kurs_oben + 20), "keine Kerzen", fill=_TEXT, font=_schrift(14))
        return

    tief, hoch = _bereich(kerzen, panel.linien)

    def y(preis: float) -> float:
        return kurs_unten - (preis - tief) / (hoch - tief) * (kurs_unten - kurs_oben)

    klein = _schrift(13)
    closes = kerzen["close"].to_numpy(dtype="float64")
    letzter = float(closes[-1])
    sichtbar = [linie for linie in panel.linien if tief <= linie.preis <= hoch]
    marken = _verteile(
        [(y(letzter), f"zuletzt {preisformat(letzter)}", _TITEL)]
        + [
            (y(linie.preis), f"{linie.text} {preisformat(linie.preis)}",
             ROLLENFARBE.get(linie.rolle, ROLLENFARBE["level"]))
            for linie in sichtbar
        ],
        kurs_oben,
        kurs_unten,
    )
    for preis in _runde_schritte(tief, hoch):
        d.line([(links, y(preis)), (rechts, y(preis))], fill=_GITTER, width=1)
        if all(abs(y(preis) - m[0]) >= _MARKE for m in marken):
            d.text((rechts + 6, y(preis) - 7), preisformat(preis), fill=_TEXT, font=klein)

    n = len(kerzen)
    breite = (rechts - links) / n
    koerper = max(1.0, breite * 0.7)
    opens = kerzen["open"].to_numpy(dtype="float64")
    highs = kerzen["high"].to_numpy(dtype="float64")
    lows = kerzen["low"].to_numpy(dtype="float64")
    volumen = kerzen["volume"].to_numpy(dtype="float64")
    ts = kerzen["ts"].to_numpy(dtype="int64")
    vol_max = float(volumen.max()) or 1.0

    for i in range(n):
        mitte = links + (i + 0.5) * breite
        farbe = _AUF if closes[i] >= opens[i] else _AB
        d.line([(mitte, y(highs[i])), (mitte, y(lows[i]))], fill=farbe, width=1)
        a, b = sorted((y(opens[i]), y(closes[i])))
        d.rectangle([mitte - koerper / 2, a, mitte + koerper / 2, max(b, a + 1)], fill=farbe)
        h = volumen[i] / vol_max * (vol_unten - vol_oben)
        d.rectangle([mitte - koerper / 2, vol_unten - h, mitte + koerper / 2, vol_unten],
                    fill=farbe)

    for i in range(0, n, max(1, n // 6)):
        zeit = datetime.fromtimestamp(ts[i] / 1000, tz=UTC).strftime("%d.%m %H:%M")
        d.text((links + i * breite, vol_unten + 4), zeit, fill=_TEXT, font=klein)

    for linie in sichtbar:
        farbe = ROLLENFARBE.get(linie.rolle, ROLLENFARBE["level"])
        if linie.rolle == "level":
            _gestrichelt(d, links, rechts, y(linie.preis), farbe)
        else:
            d.line([(links, y(linie.preis)), (rechts, y(linie.preis))], fill=farbe, width=2)
    d.line([(rechts - 4, y(letzter)), (rechts + 2, y(letzter))], fill=_TITEL, width=1)
    for marke_y, text, farbe in marken:
        d.text((rechts + 6, marke_y - 7), text, fill=farbe, font=klein)


#: Mindestabstand zweier Beschriftungen am rechten Rand, in Pixeln.
_MARKE = 15


def _verteile(
    marken: list[tuple[float, str, str]], oben: float, unten: float
) -> list[tuple[float, str, str]]:
    """Beschriftungen so verschieben, dass keine zwei sich ueberdecken.

    Die Linie bleibt, wo ihr Preis ist; nur ihr Text rueckt ab. Zwei Linien mit
    fast gleichem Preis (Einstieg am letzten Kurs) waeren sonst ein unlesbarer
    Klumpen -- und genau der Fall ist der haeufige.
    """
    geordnet = sorted(marken, key=lambda m: m[0])
    for i in range(1, len(geordnet)):
        if geordnet[i][0] - geordnet[i - 1][0] < _MARKE:
            geordnet[i] = (geordnet[i - 1][0] + _MARKE, *geordnet[i][1:])
    ueberhang = geordnet[-1][0] - unten if geordnet else 0
    if ueberhang > 0:
        geordnet = [(max(oben, m[0] - ueberhang), *m[1:]) for m in geordnet]
    return geordnet


def zeichne(panels: Sequence[Panel], *, titel: str = "") -> bytes:
    """Alle Panels untereinander, als PNG-Bytes."""
    kopf = 36 if titel else 0
    bild = Image.new("RGB", (BREITE, kopf + PANEL_HOEHE * max(1, len(panels))), _HINTERGRUND)
    d = ImageDraw.Draw(bild)
    if titel:
        d.text((_RAND_LINKS, 9), titel, fill=_TITEL, font=_schrift(18))
    for i, panel in enumerate(panels):
        _zeichne_panel(d, panel, kopf + i * PANEL_HOEHE)
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG", optimize=True)
    return puffer.getvalue()
