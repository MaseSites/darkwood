"""Grosse Trades, offenes Interesse, Positionierung — mit Beträgen.

**Warum diese Ebene nicht „institutionelle Liquidität" heisst.** Das Orderbuch
einer Börse ist anonym. Es gibt in den öffentlichen Daten kein Feld, aus dem
hervorginge, ob hinter einer Order ein Fonds oder eine Privatperson steht, und
es gibt auch keinen Umweg dorthin: eine grosse Order kann ein aufgeteilter
Kleinauftrag sein, und ein Fonds kann in tausend kleinen handeln. „Institutionell"
wäre ein Etikett, das jemand draufklebt — und ein Etikett im Chart ist genau die
Art Fehler, die dieses Projekt sich nicht leisten kann.

Was messbar ist, steht hier, und es heisst, was es misst:

    grosse Trades       einzelne Abschlüsse über einer gemessenen Schwelle
    offenes Interesse   wie viel Nominal insgesamt offen steht, und die Änderung
    Positionierung      wie die grossen Konten der Börse stehen (deren Angabe)

**Die Schwelle wird gemessen, nicht gesetzt.** „Grosse Trades ab 1 Mio USD" wäre
eine erfundene Zahl, die auf BTC etwas anderes bedeutet als auf ATOM. Stattdessen
das oberste Promille des Tages. Auf BTCUSDT am 19.10.2026 gemessen:

    Median eines Trades            249 USD
    p99.9                      711'227 USD
    grösster einzelner       31'145'512 USD
    das oberste Promille: 1'003 Trades = 1.49 Mrd USD = 14.1 % des Tagesumsatzes

**Liquidationen fehlen, und das bleibt so, bis es eine Quelle gibt.**
`allForceOrders` antwortet dieser Leitung mit der Fehlerseite der Börse, und der
WS-Strom `!forceOrder@arr` liegt auf `fstream.binance.com`, das für diese Leitung
stumm ist (zweiter unabhängiger Befund nach der WS-Messung im Oktober). Eine
Liquidationsebene zu zeichnen, deren Daten nicht ankommen, hiesse eine leere
Ebene als Messung auszugeben.
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from pydantic import BaseModel

from traidingbrain.api.volumenprofil import _tagesdatei, _tick_size, letzter_fertiger_tag

FAPI = "https://fapi.binance.com"

#: Welcher Anteil der Trades eines Tages als „gross" gilt.
#:
#: Das oberste Promille. Gemessen, nicht gewählt: bei p99 wären es 10'029
#: Trades und die Ebene wäre eine Wand aus Linien; bei p99.99 blieben hundert
#: und die Ebene wäre leer. Ein Promille ergab auf BTC 1'003 Linien über einen
#: ganzen Tag, die sich auf rund vierzig Preisstufen bündeln.
GROSS_QUANTIL = 0.999

#: Wie lange eine Live-Abfrage gilt. Die Börse begrenzt, und diese Zahlen
#: ändern sich nicht in Sekunden.
TTL = 45.0

_cache: dict[str, tuple[float, object]] = {}


def _hole(url: str, ttl: float = TTL) -> object:
    jetzt = time.time()
    tr = _cache.get(url)
    if tr and jetzt - tr[0] < ttl:
        return tr[1]
    req = urllib.request.Request(url, headers={"User-Agent": "traidingBrain/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        daten = json.loads(r.read())
    _cache[url] = (jetzt, daten)
    return daten



def _tsd(x: float, nk: int = 0) -> str:
    """Eine Zahl mit Hochkomma als Tausendertrennung.

    Nicht `f"{x:,}".replace(",", "'")` auf dem ganzen Satz: das traf die
    Kommas der Prosa mit und machte aus „1'003 Stück, zusammen" ein
    „1'003 Stück' zusammen".
    """
    return f"{x:,.{nk}f}".replace(",", "’")


# --------------------------------------------------------------------------- #
# Modelle
# --------------------------------------------------------------------------- #


class Stufe(BaseModel):
    preis: float
    usd: float
    """Nominal aller grossen Trades auf dieser Preisstufe."""

    trades: int
    kaeufer_usd: float
    """Davon mit dem Käufer als Aggressor. Der Rest war Verkäufer-getrieben."""

    groesster: float


class GrosseTrades(BaseModel):
    symbol: str
    tag: str
    schwelle_usd: float
    stufen: list[Stufe]
    gesamt_usd: float
    anzahl: int
    anteil_umsatz: float
    median_trade_usd: float
    groesster_usd: float
    quelle: str
    hinweis: str


class OiPunkt(BaseModel):
    ts: int
    usd: float
    delta_usd: float


class OffenesInteresse(BaseModel):
    symbol: str
    jetzt_usd: float
    punkte: list[OiPunkt]
    groesster_sprung_usd: float
    richtung: str
    hinweis: str


class Positionierung(BaseModel):
    symbol: str
    top_long_pct: float
    top_short_pct: float
    taker_kauf_vol: float
    taker_verkauf_vol: float
    taker_verhaeltnis: float
    hinweis: str


class Liquiditaet(BaseModel):
    symbol: str
    grosse_trades: GrosseTrades | None
    oi: OffenesInteresse | None
    positionierung: Positionierung | None
    fehlt: list[str]
    """Was es nicht gibt, und warum. Gehört ins Bild."""


# --------------------------------------------------------------------------- #
# Grosse Trades aus dem Tagesarchiv
# --------------------------------------------------------------------------- #

#: Wie viele Preisstufen die Ebene höchstens zeichnet.
STUFEN_MAX = 45

_profil_cache: dict[str, tuple[float, GrosseTrades]] = {}


def grosse_trades(symbol: str, tag: str | None = None) -> GrosseTrades | None:
    """Die grössten Abschlüsse eines abgeschlossenen Tages, nach Preis gebündelt.

    Zwei Durchgänge durch dieselbe Datei: der erste misst die Schwelle, der
    zweite bündelt, was darüber liegt. Eine Schwelle aus einem Vortag zu
    übernehmen wäre schneller und falsch — an einem ruhigen Tag läge sie zu
    hoch und die Ebene bliebe leer, ohne das zu sagen.
    """
    tag = tag or letzter_fertiger_tag()
    schluessel = f"{symbol}-{tag}"
    tr = _profil_cache.get(schluessel)
    if tr:
        return tr[1]

    roh = _tagesdatei(symbol, tag)
    if roh is None:
        return None

    zeilen: list[tuple[float, float, bool]] = []   # preis, nominal, verkaeufer_aggressiv
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        with z.open(z.namelist()[0]) as f:
            for zeile in csv.reader(io.TextIOWrapper(f, encoding="utf-8")):
                try:
                    preis = float(zeile[1])
                    menge = float(zeile[2])
                except (ValueError, IndexError):
                    continue
                # `is_buyer_maker` WAHR heisst: der VERKAEUFER hat zugeschlagen.
                zeilen.append((preis, preis * menge, str(zeile[6]).strip().lower() in ("true", "1")))

    if not zeilen:
        return None

    nominale = sorted(n for _, n, _ in zeilen)
    anzahl = len(nominale)
    schwelle = nominale[min(anzahl - 1, int(anzahl * GROSS_QUANTIL))]
    umsatz = sum(nominale)
    median = nominale[anzahl // 2]

    breite = _tick_size(zeilen[0][0])
    eimer: dict[float, list[float]] = {}
    gross_summe = 0.0
    gross_n = 0
    for preis, nominal, verkauf in zeilen:
        if nominal < schwelle:
            continue
        gross_summe += nominal
        gross_n += 1
        stufe = round(preis / breite) * breite
        e = eimer.setdefault(stufe, [0.0, 0.0, 0.0, 0.0])
        e[0] += nominal
        e[1] += 1
        if not verkauf:
            e[2] += nominal
        e[3] = max(e[3], nominal)

    # Zu feine Stufen zusammenfassen, damit die Ebene lesbar bleibt.
    while len(eimer) > STUFEN_MAX:
        breite *= 2
        grob: dict[float, list[float]] = {}
        for p, (u, n, k, g) in eimer.items():
            s = round(p / breite) * breite
            a = grob.setdefault(s, [0.0, 0.0, 0.0, 0.0])
            a[0] += u
            a[1] += n
            a[2] += k
            a[3] = max(a[3], g)
        eimer = grob

    stufen = [
        Stufe(preis=p, usd=round(u, 0), trades=int(n), kaeufer_usd=round(k, 0),
              groesster=round(g, 0))
        for p, (u, n, k, g) in sorted(eimer.items(), key=lambda x: -x[1][0])
    ]

    erg = GrosseTrades(
        symbol=symbol, tag=tag, schwelle_usd=round(schwelle, 0), stufen=stufen,
        gesamt_usd=round(gross_summe, 0), anzahl=gross_n,
        anteil_umsatz=round(100 * gross_summe / umsatz, 2) if umsatz else 0.0,
        median_trade_usd=round(median, 2), groesster_usd=round(nominale[-1], 0),
        quelle="data.binance.vision (aggTrades)",
        hinweis=(
            f"Das oberste Promille der {_tsd(anzahl)} Trades des {tag}: ab "
            f"{_tsd(schwelle)} USD je Abschluss. {_tsd(gross_n)} Stück, zusammen "
            f"{_tsd(gross_summe/1e6)} Mio USD = {100*gross_summe/umsatz:.1f} % des "
            f"Tagesumsatzes. Anonym — wer dahinter steht, steht in keinem Feld."
        ),
    )
    _profil_cache[schluessel] = (time.time(), erg)
    return erg


# --------------------------------------------------------------------------- #
# Offenes Interesse und Positionierung
# --------------------------------------------------------------------------- #


def offenes_interesse(symbol: str, period: str = "5m", limit: int = 48) -> OffenesInteresse | None:
    try:
        roh = _hole(f"{FAPI}/futures/data/openInterestHist?symbol={symbol}&period={period}&limit={limit}")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
    if not isinstance(roh, list) or not roh:
        return None

    punkte: list[OiPunkt] = []
    vorher: float | None = None
    for r in roh:
        try:
            wert = float(r["sumOpenInterestValue"])
            ts = int(r["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        punkte.append(OiPunkt(ts=ts, usd=round(wert, 0),
                              delta_usd=round(wert - vorher, 0) if vorher is not None else 0.0))
        vorher = wert
    if not punkte:
        return None

    sprung = max(punkte, key=lambda p: abs(p.delta_usd))
    gesamt_delta = punkte[-1].usd - punkte[0].usd
    return OffenesInteresse(
        symbol=symbol, jetzt_usd=punkte[-1].usd, punkte=punkte,
        groesster_sprung_usd=sprung.delta_usd,
        richtung="Aufbau" if gesamt_delta > 0 else ("Abbau" if gesamt_delta < 0 else "flach"),
        hinweis=(
            f"{punkte[-1].usd/1e9:.2f} Mrd USD stehen offen. Über die letzten "
            f"{len(punkte)} Fenster à {period}: "
            f"{'+' if gesamt_delta >= 0 else '-'}{_tsd(abs(gesamt_delta)/1e6)} Mio USD. "
            f"Offenes Interesse sagt, wie viel Position besteht — nicht, auf "
            f"welcher Seite: jedem Long steht ein Short gegenüber."
        ),
    )


def positionierung(symbol: str, period: str = "5m") -> Positionierung | None:
    try:
        top = _hole(f"{FAPI}/futures/data/topLongShortPositionRatio?symbol={symbol}&period={period}&limit=1")
        taker = _hole(f"{FAPI}/futures/data/takerlongshortRatio?symbol={symbol}&period={period}&limit=1")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
    if not (isinstance(top, list) and top and isinstance(taker, list) and taker):
        return None
    try:
        t, k = top[-1], taker[-1]
        return Positionierung(
            symbol=symbol,
            top_long_pct=round(float(t["longAccount"]) * 100, 2),
            top_short_pct=round(float(t["shortAccount"]) * 100, 2),
            taker_kauf_vol=round(float(k["buyVol"]), 2),
            taker_verkauf_vol=round(float(k["sellVol"]), 2),
            taker_verhaeltnis=round(float(k["buySellRatio"]), 4),
            hinweis=(
                "Die Börse meldet diese Anteile selbst; sie sind nicht aus Trades "
                "nachgerechnet und hier nicht prüfbar. Eine volle Long-Seite ist "
                "kein Signal in eine Richtung — sie ist ebenso oft das Futter für "
                "die Gegenbewegung."
            ),
        )
    except (KeyError, ValueError, TypeError):
        return None


FEHLT = [
    "Liquidationen: `allForceOrders` antwortet dieser Leitung mit der Fehlerseite "
    "der Börse, und der WS-Strom liegt auf fstream.binance.com, das für diese "
    "Leitung stumm ist. Keine Ebene ohne Daten.",
    "„Institutionell“ gegen „privat“: steht in keinem öffentlichen Feld und "
    "ist aus diesen Daten nicht herzuleiten. Darum heisst die Ebene "
    "„grosse Trades“.",
    "Der laufende Tag: das Tagesarchiv erscheint erst am Folgetag. Was hier steht, "
    "ist vollständig für den genannten Tag und enthält heute nicht.",
]


def liquiditaet(symbol: str, tag: str | None = None) -> Liquiditaet:
    gt = None
    if tag:
        gt = grosse_trades(symbol, tag)
    else:
        for zurueck in range(4):
            wann = letzter_fertiger_tag(time.time() - zurueck * 86400)
            gt = grosse_trades(symbol, wann)
            if gt is not None:
                break
    return Liquiditaet(
        symbol=symbol, grosse_trades=gt, oi=offenes_interesse(symbol),
        positionierung=positionierung(symbol), fehlt=list(FEHLT),
    )
