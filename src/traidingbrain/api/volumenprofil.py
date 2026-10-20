"""Das echte Volumenprofil: Umsatz je PREIS, aus den Trades der Boerse.

**Warum das nicht aus Kerzen geht.** Der Chart rechnet heute ein Profil aus
Kerzen und wirft das ganze Volumen einer Kerze auf ihren Mittelpreis. Das ist
eine Naeherung und heisst im Terminal seit dem 21.10.2026 auch so. Ein Point
of Control ist etwas anderes: der Preis, an dem die meisten Kontrakte wirklich
den Besitzer gewechselt haben. Dafuer braucht es Trades, nicht Kerzen.

**Woher die Daten kommen, und wo die Grenze liegt.**
`data.binance.vision` legt je Markt und Tag ein ZIP mit allen aggregierten
Trades ab -- oeffentlich, ohne Schluessel, zurueck bis 2020, fuer alle zwoelf
Maerkte. Die Datei fuer einen Tag erscheint am Folgetag (geprueft: der 17.10.
lag am 18.10. um 06:54 UTC bereit). Daraus folgt eine Grenze, die im Bild
stehen muss und nicht verschwiegen werden darf:

    bis gestern      vollstaendiges Profil aus jedem Trade
    heute            gar nichts aus dieser Quelle

Ein Live-Tick-Strom waere die Alternative, aber `fstream.binance.com` ist fuer
diese Leitung stumm -- zweiter unabhaengiger Befund nach der WS-Messung vom
Oktober. Der laufende Tag bleibt darum der Kerzen-Naeherung ueberlassen, und
die Oberflaeche sagt, welches von beidem sie zeigt.

**Value Area und POC, nach der ueblichen Vorschrift.** POC ist der Korb mit
dem groessten Volumen. Die Value Area waechst von dort aus: wiederholt wird
das groessere der beiden Nachbarpaare dazugenommen, bis 70 % des Gesamtvolumens
drin sind. Das ist die Definition, nach der jede Charting-Oberflaeche rechnet;
eine eigene Variante waere eine andere Groesse mit demselben Namen.
"""

from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

ARCHIV = "https://data.binance.vision/data/futures/um/daily/aggTrades"

#: Anteil des Gesamtvolumens, der in die Value Area gehoert.
VALUE_AREA = 0.70

#: Wie lange ein heruntergeladener Tag liegen bleibt. Ein vergangener Tag
#: aendert sich nie mehr, also ist die Antwort "fuer immer" -- der Cache ist
#: eine Datei auf der Platte und kein Zwischenspeicher mit Ablauf.
CACHE = Path("data") / "volumenprofil"


class Korb(BaseModel):
    preis: float
    volumen: float
    kaeufer: float          # Volumen, bei dem der Kaeufer der Aggressor war


class VolumenProfil(BaseModel):
    symbol: str
    tag: str
    koerbe: list[Korb]
    poc: float
    val: float
    vah: float
    gesamt: float
    trades: int
    quelle: str
    hinweis: str


def _tagesdatei(symbol: str, tag: str) -> bytes | None:
    """Holt ein Tagesarchiv, einmal. Liegt es schon auf der Platte, von dort."""
    CACHE.mkdir(parents=True, exist_ok=True)
    ziel = CACHE / f"{symbol}-{tag}.zip"
    if ziel.exists():
        return ziel.read_bytes()
    url = f"{ARCHIV}/{symbol}/{symbol}-aggTrades-{tag}.zip"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310
            roh = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None          # Tag noch nicht da -- kein Fehler, nur zu frueh
        raise
    ziel.write_bytes(roh)
    return roh


def _tick_size(preis: float) -> float:
    """Korbbreite, verankert an der Groessenordnung des Preises.

    **Nicht an der sichtbaren Spanne.** Ein Profil, dessen Koerbe mit dem Zoom
    wandern, liefert bei jedem Hineinzoomen einen anderen POC -- und ein POC,
    der von der Fensterbreite abhaengt, ist keine Eigenschaft des Marktes.
    """
    for grenze, breite in ((10_000, 10.0), (1_000, 1.0), (100, 0.1), (1, 0.01)):
        if preis >= grenze:
            return breite
    return 0.0001


def profil_fuer_tag(symbol: str, tag: str, koerbe_max: int = 160) -> VolumenProfil | None:
    """Das Profil eines abgeschlossenen Tages, aus jedem einzelnen Trade."""
    roh = _tagesdatei(symbol, tag)
    if roh is None:
        return None

    eimer: dict[float, list[float]] = {}
    n = 0
    breite = 0.0
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            leser = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
            for zeile in leser:
                # Die Archive tragen mal eine Kopfzeile, mal nicht.
                try:
                    preis = float(zeile[1])
                    menge = float(zeile[2])
                except (ValueError, IndexError):
                    continue
                # `is_buyer_maker` ist WAHR, wenn der VERKAEUFER zugeschlagen
                # hat. Das Vorzeichen hier falsch zu setzen, dreht die ganze
                # Aggressor-Auswertung um.
                verkauf = str(zeile[6]).strip().lower() in ("true", "1")
                if not breite:
                    breite = _tick_size(preis)
                stufe = round(preis / breite) * breite
                e = eimer.setdefault(stufe, [0.0, 0.0])
                e[0] += menge
                if not verkauf:
                    e[1] += menge
                n += 1

    if not eimer:
        return None

    # Auf eine zeichenbare Zahl zusammenfassen, falls der Tag sehr breit war.
    if len(eimer) > koerbe_max:
        faktor = -(-len(eimer) // koerbe_max)
        breite *= faktor
        grob: dict[float, list[float]] = {}
        for p, (v, k) in eimer.items():
            stufe = round(p / breite) * breite
            g = grob.setdefault(stufe, [0.0, 0.0])
            g[0] += v
            g[1] += k
        eimer = grob

    sortiert = sorted(eimer.items())
    volumina = [v for _, (v, _) in sortiert]
    gesamt = sum(volumina)
    i_poc = max(range(len(sortiert)), key=lambda i: volumina[i])
    poc = sortiert[i_poc][0]

    # Value Area: vom POC aus nach aussen, immer das groessere Nachbarpaar.
    unten = oben = i_poc
    drin = volumina[i_poc]
    ziel = gesamt * VALUE_AREA
    while drin < ziel and (unten > 0 or oben < len(sortiert) - 1):
        links = volumina[unten - 1] + (volumina[unten - 2] if unten > 1 else 0.0) if unten > 0 else -1.0
        rechts = (volumina[oben + 1] + (volumina[oben + 2] if oben < len(sortiert) - 2 else 0.0)
                  if oben < len(sortiert) - 1 else -1.0)
        if rechts > links and oben < len(sortiert) - 1:
            oben += 1
            drin += volumina[oben]
        elif unten > 0:
            unten -= 1
            drin += volumina[unten]
        else:
            break

    return VolumenProfil(
        symbol=symbol, tag=tag,
        koerbe=[Korb(preis=p, volumen=v, kaeufer=k) for p, (v, k) in sortiert],
        poc=poc, val=sortiert[unten][0], vah=sortiert[oben][0],
        gesamt=gesamt, trades=n, quelle="data.binance.vision (aggTrades)",
        hinweis=(f"Vollständiges Profil aus {n:,} Trades des {tag}. Der laufende Tag "
                 f"ist hier nicht enthalten — das Archiv erscheint erst am Folgetag."
                 ).replace(",", "'"),
    )


def letzter_fertiger_tag(jetzt: float | None = None) -> str:
    """Gestern in UTC. Heute gibt es im Archiv nicht."""
    t = datetime.fromtimestamp(jetzt or time.time(), tz=UTC)
    return (t - timedelta(days=1)).strftime("%Y-%m-%d")
