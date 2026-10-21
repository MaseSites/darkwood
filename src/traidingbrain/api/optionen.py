"""Optionen je Strike: wo Gamma liegt — ohne die Zahl zu erfinden, die fehlt.

**Warum es hier keine GEX-Linie gibt.** Gamma Exposure ist offene Kontrakte je
Strike × Black-Scholes-Gamma × **ein Vorzeichen, das in keinen öffentlichen
Daten steht**. Welche Seite die Händler halten — ob sie bei Calls short und bei
Puts long sind oder umgekehrt — ist eine Konvention, keine Messung. Nachgerechnet
am 21.10.2026 auf BTC:

    brutto (alle Vorzeichen positiv)  571'341'394 USD je 1 %
    netto  (übliche Konvention)       180'605'721 USD je 1 %

Das Vorzeichen entscheidet über zwei Drittel der angezeigten Zahl. Eine Grösse,
die auf Knopfdruck das Vorzeichen wechselt, ist keine Chart-Ebene.

**Was stattdessen hier steht, und warum es nicht bloss offenes Interesse ist.**
Reines OI je Strike würde täuschen: weit aus dem Geld liegen die grössten
Positionen, und ihr Gamma ist fast null. Der 60'000er Put auf BTC trägt 10'955
Kontrakte und bewegt bei einem Spot von 83'000 praktisch nichts. Darum wird das
Gamma wirklich gerechnet — Black-Scholes mit der Mark-IV der Börse und der
Restlaufzeit aus dem Instrumentnamen — und nur **der Betrag** gezeigt, nie das
Vorzeichen.

Eine Zeile sagt damit: *hier hängt am meisten Absicherungsbedarf, egal auf
welcher Seite.* Das ist weniger, als „GEX" verspricht, und es ist der Teil, der
in den Daten steht.

**Für welche Märkte es das gibt.** Gemessen am 21.10.2026 über alle zwölf
Märkte dieses Projekts: Deribit führt Optionen nur auf **BTC** (886
Instrumente) und **ETH** (768). Für SOL, XRP, ADA, DOGE, AVAX, LINK, LTC, DOT,
ATOM und BNB sind es null. Auf anderen Börsen gibt es vereinzelt welche — BNB
122 auf Binance, DOGE 24 —, aber bei einem Gamma von 0.155 % bzw. 0.0011 % des
Perp-Tagesvolumens ist das Rauschen und keine Ebene.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict

from pydantic import BaseModel

DERIBIT = "https://www.deribit.com/api/v2/public"

#: Welches Perp-Symbol welcher Options-Währung entspricht.
#:
#: Nur zwei Einträge, und das ist das Ergebnis einer Messung, keine Auswahl:
#: für die übrigen zehn Märkte führt Deribit null Instrumente.
WAEHRUNG: dict[str, str] = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

#: Märkte, für die es anderswo ein paar Optionen gibt, aber zu wenige.
#:
#: Die Zahlen stammen aus der Recherche vom 21.10.2026, bei der Binance und
#: Bybit abgefragt wurden. Hier stand zuerst für ALLE zehn „null Instrumente,
#: auch auf Binance und Bybit" — das war falsch und widersprach der eigenen
#: Messung: AVAX, XRP und SOL haben Optionen, nur winzige. Eine Nicht-Existenz
#: zu melden, die man nicht geprüft hat, ist derselbe Fehlertyp wie eine
#: erfundene Linie, nur in die andere Richtung.
WINZIG: dict[str, str] = {
    "BNBUSDT": "122 Optionen auf Binance, Gamma 0.155 % des Perp-Tagesvolumens",
    "AVAXUSDT": "Gamma 0.030 % des Perp-Tagesvolumens",
    "XRPUSDT": "Gamma 0.024 % des Perp-Tagesvolumens",
    "SOLUSDT": "Gamma 0.018 % des Perp-Tagesvolumens",
    "DOGEUSDT": "24 Optionen auf Binance, Gamma 0.0011 % des Perp-Tagesvolumens",
}

#: Märkte, für die am 21.10.2026 auf Deribit, Binance und Bybit nichts gefunden
#: wurde. Fünf, nicht sieben — die Siebenerzahl war ein ungeprüfter Bericht.
OHNE_OPTIONEN = ("ADAUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "ATOMUSDT")

TTL = 300.0
_cache: dict[str, tuple[float, object]] = {}

_NAME = re.compile(r"^[A-Z]+-(\d{1,2}[A-Z]{3}\d{2})-([\d.]+)-([CP])$")
_MONAT = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}



def _tsd(x: float, nk: int = 0) -> str:
    """Tausendertrennung an der ZAHL, nicht am Satz.

    `f"...".replace(",", "'")` auf dem ganzen Satz traf die Kommas der Prosa
    mit und schrieb „über 90 Strikes' Spot 84'495".
    """
    return f"{x:,.{nk}f}".replace(",", "’")


class StrikeZeile(BaseModel):
    strike: float
    call_oi: float
    put_oi: float
    gamma_usd: float
    """Betrag der Gamma-Last je 1 % Spotbewegung, in USD. OHNE Vorzeichen."""

    naechste_faelligkeit: str
    tage: float


class Optionslage(BaseModel):
    symbol: str
    waehrung: str
    spot: float
    strikes: list[StrikeZeile]
    gamma_gesamt_usd: float
    call_put_oi: float
    instrumente: int
    hinweis: str
    kein_gex: str
    verfuegbar: bool


def _hole(url: str) -> object:
    jetzt = time.time()
    tr = _cache.get(url)
    if tr and jetzt - tr[0] < TTL:
        return tr[1]
    req = urllib.request.Request(url, headers={"User-Agent": "traidingBrain/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
        d = json.loads(r.read())
    _cache[url] = (jetzt, d)
    return d


def _jahre_bis(stueck: str, jetzt: float) -> float:
    """Restlaufzeit in Jahren aus `27MAR26`. Deribit verfällt um 08:00 UTC."""
    m = re.match(r"^(\d{1,2})([A-Z]{3})(\d{2})$", stueck)
    if not m:
        return 0.0
    tag, monat, jahr = int(m.group(1)), _MONAT.get(m.group(2), 1), 2000 + int(m.group(3))
    try:
        from datetime import UTC, datetime
        ende = datetime(jahr, monat, tag, 8, 0, tzinfo=UTC).timestamp()
    except ValueError:
        return 0.0
    return max(0.0, (ende - jetzt) / (365.25 * 86400))


def _gamma(spot: float, strike: float, sigma: float, jahre: float) -> float:
    """Black-Scholes-Gamma. Zinssatz null — bei Krypto-Optionen üblich und
    bei diesen Laufzeiten unterhalb der Streuung der impliziten Volatilität."""
    if spot <= 0 or strike <= 0 or sigma <= 0 or jahre <= 0:
        return 0.0
    wurzel = sigma * math.sqrt(jahre)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * jahre) / wurzel
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (spot * wurzel)


def lage(symbol: str, max_strikes: int = 14) -> Optionslage:
    """Gamma-Last je Strike, als Betrag. Oder eine Absage mit Grund."""
    waehrung = WAEHRUNG.get(symbol.upper())
    if waehrung is None:
        grund = WINZIG.get(symbol.upper())
        return Optionslage(
            symbol=symbol, waehrung="", spot=0.0, strikes=[], gamma_gesamt_usd=0.0,
            call_put_oi=0.0, instrumente=0,
            hinweis=(
                f"Deribit führt für {symbol} keine Optionen. " + (
                    f"Anderswo: {grund} — zu wenig, um eine Ebene zu tragen."
                    if grund else
                    ("Auch auf Binance und Bybit nichts, geprüft am 21.10.2026."
                     if symbol.upper() in OHNE_OPTIONEN else
                     "Andere Börsen wurden für diesen Markt nicht geprüft.")
                )
            ),
            kein_gex="", verfuegbar=False,
        )

    try:
        antwort = _hole(f"{DERIBIT}/get_book_summary_by_currency?currency={waehrung}&kind=option")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        return Optionslage(
            symbol=symbol, waehrung=waehrung, spot=0.0, strikes=[],
            gamma_gesamt_usd=0.0, call_put_oi=0.0, instrumente=0,
            hinweis=f"Deribit nicht erreichbar: {e}", kein_gex="", verfuegbar=False,
        )

    reihen = (antwort or {}).get("result") or []
    jetzt = time.time()
    spot = 0.0
    eimer: dict[float, list] = defaultdict(lambda: [0.0, 0.0, 0.0, 1e9, ""])
    gezaehlt = 0

    for x in reihen:
        m = _NAME.match(str(x.get("instrument_name", "")))
        if not m:
            continue
        verfall, strike, cp = m.group(1), float(m.group(2)), m.group(3)
        oi = float(x.get("open_interest") or 0.0)
        iv = float(x.get("mark_iv") or 0.0) / 100.0
        s = float(x.get("underlying_price") or 0.0)
        if s > 0:
            spot = s
        jahre = _jahre_bis(verfall, jetzt)
        gezaehlt += 1

        e = eimer[strike]
        if cp == "C":
            e[0] += oi
        else:
            e[1] += oi
        # Gamma-Last je 1 % Spot: Gamma x S^2 x 0.01 x Kontrakte.
        # Ein Deribit-Kontrakt ist eine Einheit des Basiswerts.
        if oi > 0 and s > 0:
            e[2] += _gamma(s, strike, iv, jahre) * s * s * 0.01 * oi
        tage = jahre * 365.25
        if oi > 0 and tage < e[3]:
            e[3] = tage
            e[4] = verfall

    if not eimer or spot <= 0:
        return Optionslage(
            symbol=symbol, waehrung=waehrung, spot=spot, strikes=[],
            gamma_gesamt_usd=0.0, call_put_oi=0.0, instrumente=gezaehlt,
            hinweis="Keine Instrumente mit offenem Interesse.", kein_gex="",
            verfuegbar=False,
        )

    zeilen = [
        StrikeZeile(
            strike=k, call_oi=round(v[0], 1), put_oi=round(v[1], 1),
            gamma_usd=round(v[2], 0),
            naechste_faelligkeit=v[4] or "—",
            tage=round(v[3], 1) if v[3] < 1e8 else 0.0,
        )
        for k, v in eimer.items() if v[0] + v[1] > 0
    ]
    zeilen.sort(key=lambda z: -z.gamma_usd)
    zeilen = zeilen[:max_strikes]

    gesamt = sum(v[2] for v in eimer.values())
    calls = sum(v[0] for v in eimer.values())
    puts = sum(v[1] for v in eimer.values())

    return Optionslage(
        symbol=symbol, waehrung=waehrung, spot=round(spot, 2), strikes=zeilen,
        gamma_gesamt_usd=round(gesamt, 0),
        call_put_oi=round(calls / puts, 3) if puts else 0.0,
        instrumente=gezaehlt,
        hinweis=(
            f"{gezaehlt} Instrumente über {len(eimer)} Strikes, Spot "
            f"{_tsd(spot)}. Gamma-Last insgesamt {_tsd(gesamt/1e6)} Mio USD je "
            f"1 % Bewegung. Call/Put nach offenem Interesse {calls/puts:.2f}."
        ) if puts else f"{gezaehlt} Instrumente.",
        kein_gex=(
            "Keine GEX-Linie. Gamma Exposure braucht ein Vorzeichen — welche Seite "
            "die Händler halten —, und das steht in keinen öffentlichen Daten. Auf "
            "BTC macht die Konvention den Unterschied zwischen 571 und 181 Mio USD "
            "je 1 %: sie entscheidet über zwei Drittel der Zahl. Hier steht darum "
            "nur der Betrag, nie die Richtung."
        ),
        verfuegbar=True,
    )
