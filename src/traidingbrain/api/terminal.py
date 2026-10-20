"""Darkwood Terminal -- die Endpunkte, die die vier Vorlagen vom 20.10.2026 brauchen.

Die Vorlagen zeigen ein Handelsterminal mit Wirtschaftskalender, Orderbuch,
Chart mit Zonen und EMAs, einem Bot-Score aus acht Karten, einem manuellen
Orderfenster, einem Bot-Einstellungsfenster und einer Kontoseite. Dieses Modul
liefert die Daten dafuer -- und zwar nur ECHTE Daten. Die Zahlen in den
Vorlagen (Win-Rate 65 %, Bot Accuracy 85 %, 837 Trades) sind Platzhalter der
Zeichnung; hier stehen die gemessenen, und wo etwas noch nicht messbar ist,
steht das dabei statt einer erfundenen Zahl.

Alles hier ist OHNE Schluessel erreichbar: Binance-Orderbuch und Ticker sind
oeffentlich, der Kalender kommt aus dem freien ForexFactory-Feed. Ein Schluessel
wird nirgends gelesen oder geschrieben.

Das Modul liegt NICHT im Entscheidungs-Abschluss (`decision_version`), und das
ist Absicht: nichts hier aendert, welche Trades der Haendler macht. Der einzige
Weg, auf den Haendler zu wirken, ist `POST /api/terminal/bot-settings`, und
der schreibt eine Konfigurationsdatei und startet die Aufgabe neu -- eine
Aenderung, die die Laufsignatur traegt.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from traidingbrain.api.portfolio import account_equity, build_ledger
from traidingbrain.config.settings import AppConfig
from traidingbrain.journal.history import konto_schluessel
from traidingbrain.journal.record import Source
from traidingbrain.live.paperstate import PaperStateStore

BINANCE = "https://fapi.binance.com/fapi/v1"
KALENDER_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UA = {"User-Agent": "Mozilla/5.0 (traidingBrain terminal; read-only)"}

#: Roundtrip-Kosten als Bruch, dieselbe Konstante wie das Kostentor des
#: Haendlers (aus 17 bemessenen Signalen zurueckgerechnet, Streuung null).
KOSTEN_ROUNDTRIP = 0.00100000
SCHLUPF = 0.0003

ROOT = Path(__file__).resolve().parents[3]
PLAN_YAML = ROOT / "config_offen" / "plan.yaml"
RISK_YAML = ROOT / "config_offen" / "risk.yaml"
MANUELL_DB = ROOT / "data" / "manual_paper.sqlite"
PLANKONTO_AUFGABE = "traidingBrain-plankonto"


# --------------------------------------------------------------------------- #
# kleine Helfer
# --------------------------------------------------------------------------- #

_cache: dict[str, tuple[float, Any]] = {}


def _get_json(url: str, *, ttl: float, timeout: float = 12.0) -> Any:
    """GET mit Zwischenspeicher. Das Orderbuch darf jede Sekunde, der Kalender
    alle 15 Minuten -- oefter fragen hiesse die Quelle grundlos belasten."""
    jetzt = time.time()
    alt = _cache.get(url)
    if alt and jetzt - alt[0] < ttl:
        return alt[1]
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            wert = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if alt:
            return alt[1]  # lieber ein alter Wert als gar keiner -- aber `stale` meldet es
        raise HTTPException(502, f"Quelle nicht erreichbar: {type(exc).__name__}") from exc
    _cache[url] = (jetzt, wert)
    return wert


def _sterne(x: float) -> int:
    """0..1 -> 0..5 Sterne, gerundet. Fuer Prozentwerte vorher durch 100."""
    return max(0, min(5, round(max(0.0, min(1.0, x)) * 5)))


def _ps(befehl: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", befehl],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        timeout=60,
    )


# --------------------------------------------------------------------------- #
# Kopfzeile, Orderbuch, Kalender
# --------------------------------------------------------------------------- #

class Kopf(BaseModel):
    symbol: str
    last: float
    change_pct: float
    high: float
    low: float
    quote_volume: float
    mark: float | None
    funding_rate: float | None
    next_funding_ts: int | None


def kopf(symbol: str) -> Kopf:
    t = _get_json(f"{BINANCE}/ticker/24hr?symbol={symbol}", ttl=3)
    try:
        p = _get_json(f"{BINANCE}/premiumIndex?symbol={symbol}", ttl=10)
    except HTTPException:
        p = {}
    return Kopf(
        symbol=symbol,
        last=float(t["lastPrice"]),
        change_pct=float(t["priceChangePercent"]),
        high=float(t["highPrice"]),
        low=float(t["lowPrice"]),
        quote_volume=float(t["quoteVolume"]),
        mark=float(p["markPrice"]) if p.get("markPrice") else None,
        funding_rate=float(p["lastFundingRate"]) if p.get("lastFundingRate") else None,
        next_funding_ts=int(p["nextFundingTime"]) if p.get("nextFundingTime") else None,
    )


BINANCE_INTERVALL = {"M1": "1m", "M5": "5m", "M15": "15m", "H1": "1h", "H4": "4h", "D1": "1d", "W1": "1w"}


class LiveKerze(BaseModel):
    symbol: str
    timeframe: str
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool
    server_ts: int


def live_kerze(symbol: str, timeframe: str) -> LiveKerze:
    """Die Kerze, die GERADE entsteht -- plus die zuletzt geschlossene.

    Die Marktansicht des Dashboards liefert nur abgeschlossene Kerzen, weil
    die Analyse nur auf abgeschlossenen entscheidet. Fuer das Auge heisst das:
    bis zu fuenfzehn Minuten steht der Chart still, waehrend der Kurs oben in
    der Kopfzeile laeuft. Diese Kerze schliesst die Luecke. Sie ist NUR fuer
    die Zeichnung da; keine Entscheidung liest sie.
    """
    iv = BINANCE_INTERVALL.get(timeframe.upper(), "15m")
    kl = _get_json(f"{BINANCE}/klines?symbol={symbol}&interval={iv}&limit=2", ttl=2)
    k = kl[-1]
    jetzt = int(time.time() * 1000)
    return LiveKerze(
        symbol=symbol, timeframe=timeframe.upper(), ts=int(k[0]), open=float(k[1]), high=float(k[2]),
        low=float(k[3]), close=float(k[4]), volume=float(k[5]), closed=int(k[6]) < jetzt, server_ts=jetzt,
    )


class Orderbuch(BaseModel):
    symbol: str
    bids: list[list[float]]
    asks: list[list[float]]
    bid_total: float
    ask_total: float
    bid_share_pct: float
    spread_bp: float
    ts: int


#: Die Tiefen, die Binance annimmt. Jede andere Zahl ist HTTP 400 -- `limit=40`
#: sah am 20.10. aus wie "Quelle nicht erreichbar" (mein Code machte daraus
#: ein 502), war aber ein falscher Parameter. Darum hier eine Liste statt
#: eines Bereichs: ein `min(50, depth)` laesst 40 durch und luegt dann.
BINANCE_TIEFEN = (5, 10, 20, 50, 100, 500, 1000)


def orderbuch(symbol: str, depth: int = 10) -> Orderbuch:
    erlaubt = min((t for t in BINANCE_TIEFEN if t >= depth), default=BINANCE_TIEFEN[-1])
    d = _get_json(f"{BINANCE}/depth?symbol={symbol}&limit={erlaubt}", ttl=1)
    bids = [[float(p), float(q)] for p, q in d["bids"][:depth]]
    asks = [[float(p), float(q)] for p, q in d["asks"][:depth]]
    bt = sum(q for _, q in bids)
    at = sum(q for _, q in asks)
    mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else 0.0
    return Orderbuch(
        symbol=symbol, bids=bids, asks=asks, bid_total=bt, ask_total=at,
        bid_share_pct=round(bt / (bt + at) * 100, 1) if bt + at else 50.0,
        spread_bp=round((asks[0][0] - bids[0][0]) / mid * 1e4, 2) if mid else 0.0,
        ts=int(time.time() * 1000),
    )


class Heatmap(BaseModel):
    """Ruhende Buchtiefe, in Preiskoerbe gebuendelt.

    **Warum ein eigener Endpunkt und nicht die Orderbuch-Leiter.** Gemessen am
    20.10.2026 auf BTCUSDT: 20 Buchzeilen decken 6 USD ab, 100 decken 25, erst
    1000 decken 262 USD. Der Chart zeigt rund 1.500 USD Hoehe -- die Leiter mit
    ihren 40 Zeilen ist darin zwei Pixel hoch und war deshalb unsichtbar. Nicht
    kaputt, sondern zu flach.

    Die Leiter bleibt bei Tiefe 20 im Sekundentakt (sie zeigt den Spread), die
    Heatmap holt 1000 Zeilen seltener und buendelt sie hier statt im Browser:
    60 Koerbe statt 1000 Zeilen ueber die Leitung.

    **Was sie NICHT zeigt.** Was im Buch steht, muss nicht liegen bleiben: ueber
    die eigene Bandmessung verschwanden bis zu 49 % der ruhenden Orders je
    17 s, ohne dass der Preis sie erreichte. Das hier ist angezeigte Tiefe, kein
    Versprechen auf eine Ausfuehrung.
    """

    symbol: str
    mid: float
    bins: list[list[float]]  # [preis, menge, seite] -- seite +1 Gebot, -1 Brief
    max_qty: float
    low: float
    high: float
    ts: int


def heatmap(symbol: str, bins: int = 60, depth: int = 1000) -> Heatmap:
    buch = orderbuch(symbol, depth)
    bids, asks = buch.bids, buch.asks
    if not bids or not asks:
        raise HTTPException(status_code=502, detail="Orderbuch leer")
    mid = (bids[0][0] + asks[0][0]) / 2
    lo, hi = bids[-1][0], asks[-1][0]
    spanne = hi - lo
    if spanne <= 0:
        raise HTTPException(status_code=502, detail="Orderbuch ohne Spanne")
    breite = spanne / bins
    koerbe: dict[tuple[int, int], float] = {}
    for preis, menge in bids:
        koerbe[(min(bins - 1, int((preis - lo) / breite)), 1)] = (
            koerbe.get((min(bins - 1, int((preis - lo) / breite)), 1), 0.0) + menge
        )
    for preis, menge in asks:
        koerbe[(min(bins - 1, int((preis - lo) / breite)), -1)] = (
            koerbe.get((min(bins - 1, int((preis - lo) / breite)), -1), 0.0) + menge
        )
    reihen = [
        [round(lo + (i + 0.5) * breite, 8), round(q, 6), float(seite)]
        for (i, seite), q in sorted(koerbe.items())
    ]
    return Heatmap(
        symbol=symbol, mid=mid, bins=reihen,
        max_qty=max((q for _, q, _ in reihen), default=0.0),
        low=lo, high=hi, ts=int(time.time() * 1000),
    )


class KalenderEintrag(BaseModel):
    ts: int
    country: str
    title: str
    impact: str
    forecast: str
    previous: str
    actual: str
    hours_away: float


class Kalender(BaseModel):
    events: list[KalenderEintrag]
    high_within_24h: int
    next_high_hours: float | None
    risk_pct: float
    note: str


IMPACT_GEWICHT = {"High": 1.0, "Medium": 0.45, "Low": 0.15, "Holiday": 0.0}


def kalender() -> Kalender:
    roh = _get_json(KALENDER_URL, ttl=900, timeout=20)
    jetzt = time.time()
    raus: list[KalenderEintrag] = []
    for e in roh:
        try:
            ts = datetime.fromisoformat(e["date"]).timestamp()
        except (KeyError, ValueError):
            continue
        raus.append(KalenderEintrag(
            ts=int(ts * 1000), country=str(e.get("country") or ""),
            title=str(e.get("title") or ""), impact=str(e.get("impact") or "Low"),
            forecast=str(e.get("forecast") or ""), previous=str(e.get("previous") or ""),
            actual=str(e.get("actual") or ""), hours_away=round((ts - jetzt) / 3600, 1),
        ))
    raus.sort(key=lambda z: z.ts)
    kommend = [z for z in raus if z.hours_away >= -1]
    hoch24 = [z for z in kommend if z.impact == "High" and z.hours_away <= 24]
    naechste = min((z.hours_away for z in hoch24), default=None)
    # Ein "Risiko" aus der Naehe schwerer Termine: 100 % wenn in der naechsten
    # Stunde ein High-Impact-Termin liegt, abklingend ueber 24 Stunden.
    risiko = 0.0
    for z in kommend[:40]:
        w = IMPACT_GEWICHT.get(z.impact, 0.1)
        if z.hours_away <= 24:
            risiko = max(risiko, w * max(0.0, 1 - z.hours_away / 24))
    return Kalender(
        events=kommend[:30], high_within_24h=len(hoch24), next_high_hours=naechste,
        risk_pct=round(risiko * 100, 0),
        note="ForexFactory-Wochenfeed, ohne Schluessel. Zeiten in Lokalzeit des Browsers.",
    )


# --------------------------------------------------------------------------- #
# Der Bot-Score: acht Karten plus vier Chart-Karten
# --------------------------------------------------------------------------- #

class Karte(BaseModel):
    key: str
    label: str
    stars: int
    pct: float            # signiert: + fuer long, - fuer short
    direction: str        # long | short | neutral
    text: str
    measured: bool = True  # False = noch keine Messung dahinter, ehrlich gesagt


class Score(BaseModel):
    symbol: str
    direction: str
    long_pct: float
    short_pct: float
    rating: int
    band: str
    regime: str
    headline: str
    cards: list[Karte]
    chart_cards: list[Karte]
    gate_would_ask: bool
    gate_blocking: str | None


FAMILIEN_LABEL = {
    "trend": "Trend", "momentum": "Momentum", "volatility": "Volatilität",
    "volume": "Volumen", "structure": "Struktur", "location": "Lage",
    "liquidity": "Liquidität",
}


def _richtung(pct: float, schwelle: float = 8.0) -> str:
    if pct >= schwelle:
        return "long"
    if pct <= -schwelle:
        return "short"
    return "neutral"


def score(symbol: str, score_read: dict, chart: dict, buch: Orderbuch | None,
          kal: Kalender | None, history_rows: list[dict]) -> Score:
    fams = {f["family"]: f for f in score_read.get("families", [])}
    groesste = max((abs(f.get("contribution", 0.0)) for f in fams.values()), default=0.0) or 1.0

    def fam(key: str) -> tuple[float, float]:
        f = fams.get(key)
        if not f or f.get("silent"):
            return 0.0, 0.0
        pct = f["contribution"] / groesste * 100
        if f.get("direction") == "abwärts" and pct > 0:
            pct = -pct
        return pct, float(f.get("agreement", 0.0))

    bull = float(score_read.get("bullish", 0.0))
    bear = float(score_read.get("bearish", 0.0))
    long_pct = round(bull / (bull + bear) * 100, 0) if bull + bear else 50.0
    richtung = "long" if long_pct >= 58 else ("short" if long_pct <= 42 else "neutral")

    karten: list[Karte] = []

    # 1 Wirtschaftskalender
    if kal:
        k_pct = -kal.risk_pct
        karten.append(Karte(
            key="kalender", label="Wirtschaftskalender", stars=_sterne(kal.risk_pct / 100),
            pct=k_pct, direction="neutral" if kal.risk_pct < 30 else "short",
            text=(f"{kal.high_within_24h} schwere Termine in 24 h" if kal.high_within_24h
                  else "kein schwerer Termin in 24 h"),
        ))
    else:
        karten.append(Karte(key="kalender", label="Wirtschaftskalender", stars=0, pct=0,
                            direction="neutral", text="Kalender nicht erreichbar", measured=False))

    # 2 Orderbuch
    if buch:
        ob = (buch.bid_share_pct - 50) * 2  # -100..100
        karten.append(Karte(
            key="orderbuch", label="Orderbuch", stars=_sterne(abs(ob) / 100),
            pct=round(ob, 0), direction=_richtung(ob, 10),
            text=f"{buch.bid_share_pct:.0f} % Gebote, Spread {buch.spread_bp:.2f} bp",
        ))
    else:
        karten.append(Karte(key="orderbuch", label="Orderbuch", stars=0, pct=0,
                            direction="neutral", text="nicht erreichbar", measured=False))

    # 3 Chart = Struktur + Lage + Trend
    s_pct, s_ag = fam("structure"); l_pct, l_ag = fam("location"); t_pct, t_ag = fam("trend")
    chart_pct = (s_pct + l_pct + t_pct) / 3
    karten.append(Karte(
        key="chart", label="Chart", stars=_sterne((s_ag + l_ag + t_ag) / 3),
        pct=round(chart_pct, 0), direction=_richtung(chart_pct),
        text=f"Regime {score_read.get('regime', '?')}",
    ))

    # 4 Liquiditaet
    q_pct, q_ag = fam("liquidity")
    karten.append(Karte(key="liquiditaet", label="Liquidität", stars=_sterne(q_ag),
                        pct=round(q_pct, 0), direction=_richtung(q_pct), text="Pools und Sweeps"))

    # 5 Volumen
    v_pct, v_ag = fam("volume")
    karten.append(Karte(key="volumen", label="Volumen", stars=_sterne(v_ag),
                        pct=round(v_pct, 0), direction=_richtung(v_pct), text="relativ zur Spanne"))

    # 6 Price-Action = Momentum + Volatilitaet
    m_pct, m_ag = fam("momentum"); vo_pct, vo_ag = fam("volatility")
    pa = (m_pct + vo_pct) / 2
    karten.append(Karte(key="priceaction", label="Price-Action", stars=_sterne((m_ag + vo_ag) / 2),
                        pct=round(pa, 0), direction=_richtung(pa), text="Momentum und Volatilität"))

    # 7 Entry-Signal: gibt es ein Setup, und wuerde das Tor fragen?
    setups = chart.get("setups") or []
    gate = chart.get("gate") or {}
    if setups:
        s0 = setups[0]
        seite = "long" if str(s0.get("side", "")).lower().startswith("l") else "short"
        e_pct = 100 if seite == "long" else -100
        karten.append(Karte(
            key="entry", label="Entry-Signal", stars=_sterne(min(1.0, float(s0.get("reward_risk", 0)) / 4)),
            pct=e_pct, direction=seite,
            text=f"Setup {s0.get('key')} {seite} · CRV {float(s0.get('reward_risk', 0)):.2f}",
        ))
    else:
        karten.append(Karte(key="entry", label="Entry-Signal", stars=0, pct=0, direction="neutral",
                            text="kein Setup auf dieser Kerze"))

    # 8 History: dieses Symbol, die letzten geschlossenen Trades des Kontos
    eigene = [r for r in history_rows if r.get("symbol") == symbol]
    if eigene:
        treffer = sum(1 for r in eigene if float(r.get("r_multiple", 0)) > 0) / len(eigene)
        summe = sum(float(r.get("r_multiple", 0)) for r in eigene)
        h_pct = (treffer - 0.5) * 200
        karten.append(Karte(
            key="history", label="History", stars=_sterne(min(1.0, len(eigene) / 20)),
            pct=round(h_pct, 0), direction=_richtung(h_pct, 20),
            text=f"{len(eigene)} Trades · {treffer*100:.0f} % Treffer · {summe:+.2f} R",
        ))
    else:
        karten.append(Karte(key="history", label="History", stars=0, pct=0, direction="neutral",
                            text="noch kein Trade auf diesem Markt", measured=False))

    # Chart-Unterkarten
    ereignisse = chart.get("events") or []
    arten = {e.get("kind") for e in ereignisse}
    bos = sum(1 for e in ereignisse if "bos" in str(e.get("kind", "")))
    choch = sum(1 for e in ereignisse if "choch" in str(e.get("kind", "")))
    chart_karten = [
        Karte(key="zonen", label="Zonen", stars=_sterne(l_ag), pct=round(l_pct, 0),
              direction=_richtung(l_pct), text=f"{len(chart.get('bands') or [])} Zonen im Bild"),
        Karte(key="chartpattern", label="Chart-Pattern", stars=_sterne(s_ag), pct=round(s_pct, 0),
              direction=_richtung(s_pct), text=f"{bos} BOS · {choch} CHoCH"),
        Karte(key="candles", label="Candlestick-Pattern", stars=_sterne(min(1.0, len(arten) / 6)),
              pct=round(pa, 0), direction=_richtung(pa), text=f"{len(ereignisse)} Ereignisse"),
        Karte(key="trend", label="Trend", stars=_sterne(t_ag), pct=round(t_pct, 0),
              direction=_richtung(t_pct), text="über fünf Zeitebenen"),
    ]

    return Score(
        symbol=symbol, direction=richtung, long_pct=long_pct, short_pct=round(100 - long_pct, 0),
        rating=int(score_read.get("rating", 0)), band=str(score_read.get("band", "")),
        regime=str(score_read.get("regime", "")), headline=str(score_read.get("headline", "")),
        cards=karten, chart_cards=chart_karten,
        gate_would_ask=bool(gate.get("would_ask", False)), gate_blocking=gate.get("blocking"),
    )


# --------------------------------------------------------------------------- #
# Konto
# --------------------------------------------------------------------------- #

class Konto(BaseModel):
    balance: float
    start: float
    pnl_today: float
    pnl_today_pct: float
    max_drawdown_pct: float
    win_rate: float | None
    trades: int
    bot_accuracy: float | None
    bot_accuracy_n: int
    series: list[dict]
    range: str
    note: str


def konto(state_path: Path, journal_path: Path, config: AppConfig, signature: str,
          bereich: str) -> Konto:
    speicher = PaperStateStore(state_path)
    kapital, _hoch, _ = account_equity(speicher, config)
    start = config.engine.simulation.initial_equity
    led = build_ledger(journal_path, source=Source.LIVE, signature=signature)
    rows = sorted(led.rows, key=lambda r: r.closed_ts or 0)

    # Manuelle Trades dazu, wenn es welche gibt (eigene Datei, eigene Spalten).
    man = _manuell_geschlossen()
    alle = [{"closed_ts": r.closed_ts, "net_pnl": r.net_pnl, "r_multiple": r.r_multiple,
             "score_direction": r.score_direction, "side": r.side} for r in rows]
    alle += man
    alle.sort(key=lambda r: r["closed_ts"] or 0)

    jetzt_ms = int(time.time() * 1000)
    tagesanfang = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    fenster = {"today": tagesanfang, "week": jetzt_ms - 7 * 86_400_000,
               "month": jetzt_ms - 30 * 86_400_000, "all": 0}.get(bereich, 0)

    # Kapitalkurve aus dem Journal: Start plus kumulierte Netto-Ergebnisse.
    kurve = [{"ts": alle[0]["closed_ts"] - 1 if alle else jetzt_ms - 1, "equity": start}]
    lauf = start
    for r in alle:
        lauf += float(r["net_pnl"] or 0.0)
        kurve.append({"ts": int(r["closed_ts"]), "equity": round(lauf, 2)})
    kurve.append({"ts": jetzt_ms, "equity": round(kapital, 2)})

    # Max Drawdown ueber die ganze Kurve, vom Hoechststand.
    spitze, dd = start, 0.0
    for p in kurve:
        spitze = max(spitze, p["equity"])
        if spitze > 0:
            dd = max(dd, (spitze - p["equity"]) / spitze)

    heute = [r for r in alle if (r["closed_ts"] or 0) >= tagesanfang]
    pnl_heute = sum(float(r["net_pnl"] or 0.0) for r in heute)
    sichtbar = [r for r in alle if (r["closed_ts"] or 0) >= fenster]
    gewinner = sum(1 for r in sichtbar if float(r["r_multiple"] or 0.0) > 0)

    # "Bot Accuracy" -- EHRLICH definiert: Anteil der Trades, bei denen die
    # Richtung des Scores (zur Entscheidungszeit) mit dem Vorzeichen des
    # Ergebnisses zusammenfiel. Nichts anderes ist aus den Daten belegbar.
    bewertbar = [r for r in sichtbar if r.get("score_direction") in ("aufwärts", "abwärts")]
    treffer = 0
    for r in bewertbar:
        seite_long = str(r.get("side", "")).lower().startswith("l")
        score_long = r["score_direction"] == "aufwärts"
        gewonnen = float(r["r_multiple"] or 0.0) > 0
        # Score und Seite gleich UND gewonnen, oder Score gegen Seite UND verloren.
        treffer += int((score_long == seite_long) == gewonnen)

    return Konto(
        balance=round(kapital, 2), start=start, pnl_today=round(pnl_heute, 2),
        pnl_today_pct=round(pnl_heute / start * 100, 2) if start else 0.0,
        max_drawdown_pct=round(-dd * 100, 1),
        win_rate=round(gewinner / len(sichtbar) * 100, 0) if sichtbar else None,
        trades=len(sichtbar),
        bot_accuracy=round(treffer / len(bewertbar) * 100, 0) if bewertbar else None,
        bot_accuracy_n=len(bewertbar),
        series=[p for p in kurve if p["ts"] >= fenster] or kurve[-2:],
        range=bereich,
        note=("Win-Rate und Bot-Genauigkeit stehen erst ab 30 Trades fest; "
              "darunter sind sie eine Momentaufnahme."),
    )


# --------------------------------------------------------------------------- #
# Bot-Einstellungen (lesen / anwenden)
# --------------------------------------------------------------------------- #

class BotSettings(BaseModel):
    initial_margin_usd: float
    margin_pct: float = Field(ge=1, le=100)
    max_leverage: bool
    leverage: float = Field(ge=1, le=50)
    max_loss_pct: float = Field(ge=0.1, le=50)
    min_loss_pct: float = Field(ge=0.0, le=50)
    always_max_risk: bool
    fix_crv: bool
    crv: float = Field(ge=0.1, le=20)
    auto_trader: bool
    min_bot_rating: int = Field(ge=0, le=100)
    risk_cap_pct: float | None = None


class BotSettingsView(BotSettings):
    balance: float
    trader_running: bool
    signature: str
    note: str
    wirkung: dict[str, str]


def _lese_plan_yaml() -> dict:
    if PLAN_YAML.exists():
        return yaml.safe_load(PLAN_YAML.read_text(encoding="utf-8")) or {}
    return {}


def _trader_laeuft() -> bool:
    r = _ps(f'(Get-ScheduledTask -TaskName "{PLANKONTO_AUFGABE}").State')
    return "Running" in (r.stdout or "")


def bot_settings_lesen(state_path: Path, config: AppConfig, signature: str) -> BotSettingsView:
    speicher = PaperStateStore(state_path)
    kapital, _, _ = account_equity(speicher, config)
    p = _lese_plan_yaml()
    margin_pct = float(p.get("margin_share", 0.30)) * 100
    hebel = float(p.get("leverage", 7.0))
    # Von der PLATTE, nicht aus der zwischengespeicherten Konfiguration: nach
    # einem Apply steht in risk.yaml schon der neue Wert, waehrend `config`
    # bis zum Neustart den alten traegt. Das Formular soll zeigen, was gilt.
    min_rr = float(config.risk.limits.min_reward_risk)
    if RISK_YAML.exists():
        import re
        m = re.search(r"^\s*min_reward_risk:\s*([0-9.]+)", RISK_YAML.read_text(encoding="utf-8"), re.M)
        if m:
            min_rr = float(m.group(1))
    return BotSettingsView(
        initial_margin_usd=round(kapital * margin_pct / 100, 2),
        margin_pct=round(margin_pct, 1),
        max_leverage=bool(p.get("max_leverage", False)),
        leverage=hebel,
        max_loss_pct=float(p.get("max_risk_share", 0.35)) * 100,
        min_loss_pct=float(p.get("min_risk_share", 0.0)) * 100,
        always_max_risk=bool(p.get("always_max_risk", True)),
        fix_crv=min_rr >= 1.0,
        crv=min_rr if min_rr >= 1.0 else 4.0,
        auto_trader=_trader_laeuft(),
        min_bot_rating=int(p.get("min_bot_rating", 0)),
        risk_cap_pct=(float(p["risk_cap_share"]) * 100 if p.get("risk_cap_share") is not None else None),
        balance=round(kapital, 2),
        trader_running=_trader_laeuft(),
        signature=signature,
        note=("Apply schreibt config_offen/plan.yaml und risk.yaml und startet den Haendler "
              "neu. Die Laufsignatur traegt die Aenderung; Trades davor und danach bleiben "
              "trennbar."),
        wirkung={
            "margin_pct": "Positionsgroesse = Kapital x Margin x Hebel (sofort nach Neustart)",
            "leverage": "Hebel der Planregel (sofort nach Neustart)",
            "max_loss_pct": "Deckel auf das Risiko je Trade, im Sizer geprueft",
            "risk_cap_pct": "Deckelt das Risiko je Trade und KUERZT dafuer die Position. Gegengerechnet an den elf Trades vom 20.10.: -13.75 statt -90.18 USD.",
            "min_loss_pct": "NOCH OHNE WIRKUNG -- der Sizer kennt keinen Boden; gespeichert wird es.",
            "fix_crv": "Mindest-Chance-Risiko im Tor (risk.yaml)",
            "auto_trader": "startet oder stoppt die Aufgabe traidingBrain-plankonto",
            "min_bot_rating": "NOCH OHNE WIRKUNG -- das Tor dafuer liegt im Entscheidungs-"
                              "code und wird erst nach E17 angefasst; gespeichert wird es.",
        },
    )


def bot_settings_anwenden(s: BotSettings) -> dict:
    """Schreibt die Dateien, startet den Haendler neu. Rueckgabe: was passiert ist."""
    PLAN_YAML.parent.mkdir(parents=True, exist_ok=True)
    # Den Deckel aus der Datei uebernehmen, wenn das Formular keinen schickt --
    # sonst loescht ein "Apply" aus dem Terminal still die wichtigste
    # Risikoeinstellung des Kontos.
    vorher = _lese_plan_yaml()
    deckel = (s.risk_cap_pct / 100) if s.risk_cap_pct is not None else vorher.get("risk_cap_share")
    plan = {
        "margin_share": round(s.margin_pct / 100, 4),
        "leverage": float(s.leverage),
        "max_leverage": bool(s.max_leverage),
        "max_risk_share": round(s.max_loss_pct / 100, 4),
        "min_risk_share": round(s.min_loss_pct / 100, 4),
        "always_max_risk": bool(s.always_max_risk),
        "min_bot_rating": int(s.min_bot_rating),
        "risk_cap_share": deckel,
        "geschrieben": datetime.now(timezone.utc).isoformat(),
        "hinweis": "Vom Terminal geschrieben. plantrade.py liest diese Datei, wenn sie existiert.",
    }
    PLAN_YAML.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Chance-Risiko-Tor in risk.yaml: nur die eine Zeile, Rest unangetastet.
    if RISK_YAML.exists():
        text = RISK_YAML.read_text(encoding="utf-8")
        neu = s.crv if s.fix_crv else 0.01
        import re
        text2 = re.sub(r"(^\s*min_reward_risk:\s*)[0-9.]+", rf"\g<1>{neu:g}", text, flags=re.M)
        if text2 != text:
            RISK_YAML.write_text(text2, encoding="utf-8")

    schritte = []
    # Das Dashboard selbst muss AUCH neu starten: seine Konfiguration ist beim
    # Start gelesen und zwischengespeichert, und die Laufsignatur haengt am
    # Chance-Risiko und am Zusatz aus plan.yaml. Ohne Neustart suchte es die
    # Trades des Haendlers ab dem ersten Apply unter dem alten Schluessel.
    # Abgesetzt und NICHT abgewartet, damit diese Antwort noch ankommt; die
    # Seite laedt sich nach einer halben Minute selbst nach.
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         'Start-Sleep -Seconds 4; Stop-ScheduledTask -TaskName "traidingBrain-dash-plan"; '
         'Start-Sleep -Seconds 3; Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | '
         'Where-Object { $_.CommandLine -like "*run_dashboard*plan*" } | '
         'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; '
         'Start-Sleep -Seconds 2; Start-ScheduledTask -TaskName "traidingBrain-dash-plan"'],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )
    schritte.append("Dashboard startet in ~5 s neu")
    if s.auto_trader:
        r = _ps(f'Stop-ScheduledTask -TaskName "{PLANKONTO_AUFGABE}"; Start-Sleep -Seconds 3; '
                f'Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | '
                f'Where-Object {{ $_.CommandLine -like "*plantrade*" }} | '
                f'ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}; '
                f'Start-Sleep -Seconds 2; Start-ScheduledTask -TaskName "{PLANKONTO_AUFGABE}"; "neu gestartet"')
        schritte.append(f"Haendler: {(r.stdout or r.stderr).strip()[:120]}")
    else:
        r = _ps(f'Stop-ScheduledTask -TaskName "{PLANKONTO_AUFGABE}"; '
                f'Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | '
                f'Where-Object {{ $_.CommandLine -like "*plantrade*" }} | '
                f'ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}; "gestoppt"')
        schritte.append(f"Haendler: {(r.stdout or r.stderr).strip()[:120]}")
    return {"ok": True, "plan_yaml": str(PLAN_YAML), "schritte": schritte}


# --------------------------------------------------------------------------- #
# Manuelles Papierkonto (eigene Datei, nie das Konto des Haendlers)
# --------------------------------------------------------------------------- #

def _manuell_db() -> sqlite3.Connection:
    MANUELL_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(MANUELL_DB, timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS positions (
        id TEXT PRIMARY KEY, symbol TEXT, side TEXT, qty REAL, entry REAL, leverage REAL,
        margin REAL, tp REAL, sl REAL, opened_ts INTEGER, status TEXT, exit REAL,
        closed_ts INTEGER, pnl REAL, fees REAL, reason TEXT, last_check_ts INTEGER)""")
    return con


class OrderWunsch(BaseModel):
    symbol: str
    side: str = Field(pattern="^(long|short)$")
    margin_usd: float = Field(gt=0)
    leverage: float = Field(ge=1, le=50)
    tp: float | None = None
    sl: float | None = None


def order_oeffnen(w: OrderWunsch) -> dict:
    k = kopf(w.symbol)
    preis = k.last * (1 + SCHLUPF if w.side == "long" else 1 - SCHLUPF)
    notional = w.margin_usd * w.leverage
    qty = notional / preis
    fee_in = notional * KOSTEN_ROUNDTRIP / 2
    if w.sl is not None and ((w.side == "long" and w.sl >= preis) or (w.side == "short" and w.sl <= preis)):
        raise HTTPException(422, "Stop liegt auf der falschen Seite des Einstiegs.")
    if w.tp is not None and ((w.side == "long" and w.tp <= preis) or (w.side == "short" and w.tp >= preis)):
        raise HTTPException(422, "Ziel liegt auf der falschen Seite des Einstiegs.")
    pid = uuid.uuid4().hex[:12]
    with closing(_manuell_db()) as con:
        con.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, w.symbol, w.side, qty, preis, w.leverage, w.margin_usd, w.tp, w.sl,
                     int(time.time() * 1000), "open", None, None, None, fee_in, None,
                     int(time.time() * 1000)))
        con.commit()
    return {"id": pid, "entry": preis, "qty": qty, "fees_so_far": fee_in}


def _schliesse(con: sqlite3.Connection, row: sqlite3.Row, preis: float, ts: int, grund: str) -> None:
    qty, entry, side = float(row["qty"]), float(row["entry"]), row["side"]
    brutto = (preis - entry) * qty if side == "long" else (entry - preis) * qty
    fee_out = qty * preis * KOSTEN_ROUNDTRIP / 2
    fees = float(row["fees"] or 0.0) + fee_out
    con.execute("UPDATE positions SET status='closed', exit=?, closed_ts=?, pnl=?, fees=?, reason=? WHERE id=?",
                (preis, ts, brutto - fees, fees, grund, row["id"]))


def positionen_abrechnen() -> None:
    """TP/SL gegen echte Minutenkerzen pruefen. Stop vor Ziel bei Gleichstand."""
    with closing(_manuell_db()) as con:
        con.row_factory = sqlite3.Row
        offen = con.execute("SELECT * FROM positions WHERE status='open'").fetchall()
        for row in offen:
            if row["tp"] is None and row["sl"] is None:
                continue
            seit = int(row["last_check_ts"] or row["opened_ts"])
            try:
                kl = _get_json(f"{BINANCE}/klines?symbol={row['symbol']}&interval=1m&startTime={seit}&limit=1000", ttl=5)
            except HTTPException:
                continue
            long = row["side"] == "long"
            tp, sl = row["tp"], row["sl"]
            for k in kl:
                hi, lo, ts = float(k[2]), float(k[3]), int(k[0])
                stop_tr = sl is not None and ((lo <= sl) if long else (hi >= sl))
                ziel_tr = tp is not None and ((hi >= tp) if long else (lo <= tp))
                if stop_tr:
                    _schliesse(con, row, float(sl) * (1 - SCHLUPF if long else 1 + SCHLUPF), ts + 59_999, "stop")
                    break
                if ziel_tr:
                    _schliesse(con, row, float(tp), ts + 59_999, "target")
                    break
            else:
                con.execute("UPDATE positions SET last_check_ts=? WHERE id=?",
                            (int(kl[-1][0]) if kl else seit, row["id"]))
        con.commit()


def positionen_offen() -> list[dict]:
    positionen_abrechnen()
    with closing(_manuell_db()) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM positions WHERE status='open' ORDER BY opened_ts DESC").fetchall()
    raus = []
    for r in rows:
        try:
            last = kopf(r["symbol"]).last
        except HTTPException:
            last = float(r["entry"])
        qty, entry = float(r["qty"]), float(r["entry"])
        unreal = (last - entry) * qty if r["side"] == "long" else (entry - last) * qty
        raus.append({
            "id": r["id"], "symbol": r["symbol"], "side": r["side"], "qty": qty, "entry": entry,
            "leverage": r["leverage"], "margin": r["margin"], "tp": r["tp"], "sl": r["sl"],
            "opened_ts": r["opened_ts"], "last": last, "unrealized": round(unreal - float(r["fees"] or 0), 2),
            "position_size": round(qty * entry, 2), "source": "manuell",
        })
    return raus


def position_schliessen(pid: str) -> dict:
    with closing(_manuell_db()) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM positions WHERE id=? AND status='open'", (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "keine offene Position mit dieser Kennung")
        k = kopf(row["symbol"])
        preis = k.last * (1 - SCHLUPF if row["side"] == "long" else 1 + SCHLUPF)
        _schliesse(con, row, preis, int(time.time() * 1000), "manual")
        con.commit()
    return {"ok": True, "exit": preis}


def position_tp_sl(pid: str, tp: float | None, sl: float | None) -> dict:
    with closing(_manuell_db()) as con:
        con.execute("UPDATE positions SET tp=?, sl=? WHERE id=? AND status='open'", (tp, sl, pid))
        con.commit()
    return {"ok": True}


#: Zerlegt einen Kontozusatz: Name, Marginanteil, Hebel, Deckel, Bremsen frei.
#:
#: **Von Hand zerlegt ging das schief, und zwar sofort.** Hier stand ein
#: `rest.split("r", 1)` mit `float(deckel)`. Als der Zusatz am 20.10. abends
#: ein `f` fuer geloeste Verlustbremsen bekam, lief das auf `float("15f")` --
#: und das Dashboard startete nicht mehr. Ein Format, das waechst, braucht
#: einen Parser, der das Unbekannte stehen laesst, statt eines, der annimmt,
#: er kenne das letzte Zeichen.
_ZUSATZ = re.compile(r"^(?P<konto>[a-z]+)(?P<anteil>\d+)x(?P<hebel>[\d.]+)"
                     r"(?:r(?P<deckel>[\d.]+))?(?P<frei>f)?$")


def _regel(signatur: str | None) -> str:
    """Die Groessenregel als kurzes Etikett: `30%x7 · Deckel 1.5% · Bremsen frei`."""
    if not signatur:
        return "?"
    treffer = _ZUSATZ.match(signatur.rsplit("|", 1)[-1])
    if treffer is None:
        return "?"
    teile = [f"{treffer['anteil']}%x{treffer['hebel']}"]
    if treffer["deckel"]:
        teile.append(f"Deckel {float(treffer['deckel']) / 10:g}%")
    if treffer["frei"]:
        teile.append("Bremsen frei")
    return " · ".join(teile)


def _frueheres_konto(journal_pfad: Path, aktuelle: str | None) -> list[dict]:
    """Trades DESSELBEN Kontos unter einer frueheren Groessenregel.

    Dasselbe Konto heisst: derselbe Signaturzusatz bis auf den Regelteil --
    `...|plan30x7` und `...|plan30x7r15` sind dasselbe Papierkonto, nur vor
    und nach der Umstellung vom 20.10. abends. Ein anderes Konto (`live`, ohne
    Zusatz) kommt hier NICHT herein; das war der Fehler, der dem Plankonto
    einmal -63.81 USD auf BTCUSDT zeigte, die ein anderes Konto gemacht hatte.

    **Die Regel kommt aus `journal/history.konto_schluessel` und wird hier
    nicht nachgebaut.** Vorher stand hier ein eigener Praefix-Vergleich auf
    dem Wort "plan", der nur fuer ein so benanntes Konto funktionierte. Zwei
    Fassungen derselben Regel driften, und dieselbe Regel entscheidet seit dem
    20.10. abends auch, was die Verlustbremsen sehen -- eine Abweichung waere
    dann nicht kosmetisch, sondern eine Anzeige, die ein anderes Konto zeigt
    als die Bremse zaehlt.
    """
    if not aktuelle:
        return []
    schluessel = konto_schluessel(aktuelle)
    if not schluessel[1]:  # kein Kontozusatz -- es gibt keine frueheren Regeln
        return []
    con = sqlite3.connect(f"file:{journal_pfad}?mode=ro", uri=True, timeout=20)
    raus: list[dict] = []
    try:
        for pl, in con.execute("SELECT payload FROM trades WHERE payload IS NOT NULL"):
            try:
                p = json.loads(pl)
            except json.JSONDecodeError:
                continue
            sig = p.get("run_signature") or ""
            if konto_schluessel(sig) != schluessel or sig == aktuelle:
                continue
            if not p.get("closed_ts"):
                continue
            pm = p.get("post_mortem") or {}
            rs = p.get("reason") or {}
            raus.append({
                "closed_ts": p.get("closed_ts"), "opened_ts": p.get("opened_ts"),
                "symbol": p.get("symbol"), "side": rs.get("side"),
                "entry": p.get("entry_price"), "exit": p.get("exit_price"),
                "tp": rs.get("target"), "sl": rs.get("stop"), "net_pnl": p.get("net_pnl"),
                "fees": p.get("fees"), "r_multiple": p.get("r_multiple"),
                "exit_reason": p.get("exit_reason"), "setup": rs.get("setup_key"),
                "rating": rs.get("rating"), "max_favourable_r": pm.get("max_favourable_r"),
                "stopped_by_wick": pm.get("stopped_by_wick"), "verdict": pm.get("verdict"),
                "source": "bot", "position_size": None, "leverage": p.get("leverage"),
                "regel": _regel(sig), "aktuell": False,
            })
    finally:
        con.close()
    return raus


def _manuell_geschlossen() -> list[dict]:
    if not MANUELL_DB.exists():
        return []
    with closing(_manuell_db()) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM positions WHERE status='closed' ORDER BY closed_ts DESC").fetchall()
    raus = []
    for r in rows:
        risiko = abs(float(r["entry"]) - float(r["sl"])) * float(r["qty"]) if r["sl"] else float(r["margin"])
        raus.append({
            "closed_ts": r["closed_ts"], "opened_ts": r["opened_ts"], "symbol": r["symbol"],
            "side": r["side"], "entry": r["entry"], "exit": r["exit"], "qty": r["qty"],
            "leverage": r["leverage"], "position_size": round(float(r["qty"]) * float(r["entry"]), 2),
            "tp": r["tp"], "sl": r["sl"], "net_pnl": r["pnl"], "fees": r["fees"],
            "r_multiple": round(float(r["pnl"] or 0) / risiko, 4) if risiko else 0.0,
            "exit_reason": r["reason"], "source": "manuell", "score_direction": None,
        })
    return raus


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #

def router(services: Any, konto_signatur, state_path, journal_path, followed) -> APIRouter:
    """`services` und die drei Helfer kommen aus `api/app.py`, damit dieses Modul
    dieselbe Signatur, denselben Speicher und dieselbe Marktliste benutzt wie
    die uebrigen Endpunkte -- und nicht eine zweite Vorstellung davon."""
    r = APIRouter(prefix="/api/terminal", tags=["terminal"])

    @r.get("/head/{symbol}", response_model=Kopf)
    def _head(symbol: str) -> Kopf:
        return kopf(symbol.upper())

    @r.get("/live-candle/{symbol}", response_model=LiveKerze)
    def _live(symbol: str, tf: str = "M15") -> LiveKerze:
        return live_kerze(symbol.upper(), tf)

    @r.get("/orderbook/{symbol}", response_model=Orderbuch)
    def _ob(symbol: str, depth: int = 10) -> Orderbuch:
        return orderbuch(symbol.upper(), depth)

    @r.get("/heatmap/{symbol}", response_model=Heatmap)
    def _heat(symbol: str, bins: int = 60) -> Heatmap:
        return heatmap(symbol.upper(), bins)

    @r.get("/calendar", response_model=Kalender)
    def _cal() -> Kalender:
        return kalender()

    @r.get("/score/{symbol}", response_model=Score)
    def _score(symbol: str) -> Score:
        symbol = symbol.upper()
        from traidingbrain.api.app import _score_read_dict, _chart_dict  # spaet, gegen Zirkel
        sr = _score_read_dict(services, symbol)
        ch = _chart_dict(services, symbol)
        try:
            buch = orderbuch(symbol, 10)
        except HTTPException:
            buch = None
        try:
            kal = kalender()
        except HTTPException:
            kal = None
        led = build_ledger(journal_path(services), source=Source.LIVE, signature=konto_signatur(services))
        rows = [{"symbol": x.symbol, "r_multiple": x.r_multiple} for x in led.rows]
        return score(symbol, sr, ch, buch, kal, rows)

    @r.get("/account", response_model=Konto)
    def _konto(range: str = "month") -> Konto:
        return konto(state_path(services), journal_path(services), services.config,
                     konto_signatur(services), range)

    @r.get("/bot-settings", response_model=BotSettingsView)
    def _bs() -> BotSettingsView:
        return bot_settings_lesen(state_path(services), services.config, konto_signatur(services))

    @r.post("/bot-settings")
    def _bs_apply(s: BotSettings) -> dict:
        return bot_settings_anwenden(s)

    @r.post("/order")
    def _order(w: OrderWunsch) -> dict:
        w.symbol = w.symbol.upper()
        return order_oeffnen(w)

    @r.get("/positions")
    def _positions() -> list[dict]:
        return positionen_offen()

    @r.post("/positions/{pid}/close")
    def _close(pid: str) -> dict:
        return position_schliessen(pid)

    @r.post("/positions/{pid}/tpsl")
    def _tpsl(pid: str, tp: float | None = None, sl: float | None = None) -> dict:
        return position_tp_sl(pid, tp, sl)

    @r.get("/history")
    def _history(limit: int = 50, alle_regeln: bool = True) -> list[dict]:
        """Die abgeschlossenen Trades DIESES Kontos.

        `alle_regeln=True` zeigt auch die Trades unter einer FRUEHEREN
        Groessenregel desselben Kontos. Das ist Absicht und keine Nachlaessig-
        keit: am 20.10. abends bekam das Konto einen Risikodeckel, der
        Signaturzusatz wechselte von `plan30x7` auf `plan30x7r15`, und mit
        strenger Filterung waere die Trade-Ansicht schlagartig leer gewesen --
        elf Trades, die es wirklich gab, unsichtbar.

        Jede Zeile traegt darum `regel`, und die Statistik oben in der Ansicht
        rechnet weiter je Regel. Zusammenmitteln darf man sie nicht: unter der
        alten Regel riskierte ein Trade 4.95 bis 46.66 USD, unter der neuen
        hoechstens 1.5 % des Kontos. In R sind sie vergleichbar, in Dollar
        nicht.
        """
        sig = konto_signatur(services)
        led = build_ledger(journal_path(services), source=Source.LIVE, signature=sig)
        plan = [{
            "closed_ts": x.closed_ts, "opened_ts": x.opened_ts, "symbol": x.symbol, "side": x.side,
            "entry": x.entry, "exit": x.exit, "tp": x.target, "sl": x.stop, "net_pnl": x.net_pnl,
            "fees": x.fees, "r_multiple": x.r_multiple, "exit_reason": x.exit_reason,
            "setup": x.setup, "rating": x.rating, "max_favourable_r": x.max_favourable_r,
            "stopped_by_wick": x.stopped_by_wick, "verdict": x.verdict, "source": "bot",
            "position_size": None, "leverage": None, "regel": _regel(sig), "aktuell": True,
        } for x in led.rows]
        if alle_regeln:
            plan += _frueheres_konto(journal_path(services), sig)
        alle = plan + _manuell_geschlossen()
        alle.sort(key=lambda z: z["closed_ts"] or 0, reverse=True)
        return alle[:limit]

    return r
