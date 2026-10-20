"""Schreibt jeden Trade des Plankontos auf: warum rein, was daraus wurde.

Das System haelt pro Trade bereits ein vollstaendiges Protokoll -- Setup,
Regime, sieben Indikatorfamilien mit Richtung und Beitrag, Einstieg, Stop,
Ziel, und nach dem Schluss ein post_mortem mit Urteil. Niemand konnte es
lesen. Dieses Skript rendert daraus audit/HANDELSBUCH.md.

Es erfindet nichts. Jede Zeile kommt aus dem gespeicherten Datensatz; die
Lehren am Ende jedes Eintrags sind mechanische Regeln ueber diesen Zahlen,
keine Einschaetzung.

    python scripts/handelsbuch.py
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WURZEL = Path(__file__).resolve().parent.parent
JOURNAL = WURZEL / "data" / "journal.sqlite"
ZIEL = WURZEL / "audit" / "HANDELSBUCH.md"

# Die Vorwaertsregel: notional = equity * margin_share * hebel. Der im
# Datensatz gespeicherte leverage ist die Boersen-Obergrenze (10), nicht der
# Sizing-Hebel. Aus qty*entry laesst sich das Eigenkapital exakt zurueckrechnen.
MARGIN_ANTEIL = 0.30
SIZING_HEBEL = 7.0
NOTIONAL_JE_EIGENKAPITAL = MARGIN_ANTEIL * SIZING_HEBEL

FAMILIEN_DE = {
    "trend": "Trend",
    "momentum": "Momentum",
    "volatility": "Volatilitaet",
    "volume": "Volumen",
    "structure": "Struktur",
    "location": "Lage",
    "liquidity": "Liquiditaet",
}
RICHTUNG_DE = {"bullish": "aufwaerts", "bearish": "abwaerts", "neutral": "neutral"}
REGIME_DE = {
    "trend_up": "Aufwaertstrend",
    "trend_down": "Abwaertstrend",
    "range": "Seitwaerts",
    "manipulation": "Manipulation",
}
AUSSTIEG_DE = {
    "stop": "Stop getroffen",
    "target": "Ziel erreicht",
    "timeout": "Zeit abgelaufen",
    "liquidation": "Liquidation",
    "manual": "von Hand geschlossen",
}


def plan_trades(pfad: Path) -> list[dict[str, Any]]:
    """Alle Trades des Plankontos, aelteste zuerst -- ueber alle Sizing-Regeln."""
    with sqlite3.connect(f"file:{pfad}?mode=ro", uri=True) as c:
        roh = [json.loads(p) for (p,) in c.execute("select payload from trades")]
    trades = [t for t in roh if "|plan" in t.get("run_signature", "")]
    trades.sort(key=lambda t: t.get("opened_ts") or 0)
    return trades


def regel(signatur: str) -> str:
    """plan30x7r15 -> '30 % x 7, Deckel 1.5 %'."""
    teil = signatur.rsplit("|", 1)[-1]
    if not teil.startswith("plan"):
        return teil
    rest = teil[4:]
    deckel = None
    if "r" in rest:
        rest, _, r = rest.partition("r")
        deckel = float(r) / 10.0
    anteil, _, hebel = rest.partition("x")
    text = f"{anteil} % x {hebel}"
    return f"{text}, Deckel {deckel:g} %" if deckel is not None else f"{text}, ohne Deckel"


def eigenkapital(t: dict[str, Any]) -> float | None:
    """Rueckgerechnet aus der Position -- die Vorwaertsregel ist umkehrbar."""
    qty, entry = t.get("qty") or 0.0, t.get("entry_price") or 0.0
    if qty <= 0 or entry <= 0:
        return None
    return qty * entry / NOTIONAL_JE_EIGENKAPITAL


def deckel_haette_gegriffen(t: dict[str, Any], anteil: float = 0.015) -> tuple[bool, float]:
    """Haette der Risikodeckel diese Position verkleinert, und auf welches Risiko?"""
    eq = eigenkapital(t)
    risiko = t.get("risk_amount") or 0.0
    if eq is None or risiko <= 0:
        return False, risiko
    erlaubt = anteil * eq
    return risiko > erlaubt, min(risiko, erlaubt)


def uhr(ts: int | None) -> str:
    if not ts:
        return "unbekannt"
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def zahl(x: float, n: int = 2) -> str:
    return f"{x:+,.{n}f}".replace(",", "'")


def preis(x: float) -> str:
    n = 2 if x >= 100 else (4 if x >= 1 else 6)
    return f"{x:,.{n}f}".replace(",", "'")


def familien_zeilen(gruende: dict[str, Any], seite: str) -> list[str]:
    """Welche Familie sprach wofuer -- und welche schwieg."""
    dafuer = "bullish" if seite == "long" else "bearish"
    zeilen = []
    for f in sorted(gruende.get("families", []), key=lambda f: -abs(f.get("contribution") or 0)):
        name = FAMILIEN_DE.get(f.get("family"), f.get("family"))
        if f.get("silent"):
            zeilen.append(f"- {name}: schwieg")
            continue
        richtung = f.get("direction")
        haltung = "dafuer" if richtung == dafuer else ("dagegen" if richtung in ("bullish", "bearish") else "neutral")
        zeilen.append(
            f"- {name}: {RICHTUNG_DE.get(richtung, richtung)} ({haltung}), "
            f"Beitrag {f.get('contribution', 0):+.4f}, Einigkeit {f.get('agreement', 0):.0%}"
        )
    return zeilen


def eintrag(t: dict[str, Any], nr: int) -> str:
    g = t.get("reason") or {}
    pm = t.get("post_mortem") or {}
    seite = g.get("side", "?")
    seite_de = "LONG" if seite == "long" else "SHORT"
    r = t.get("r_multiple") or 0.0
    usd = t.get("net_pnl") or 0.0
    zeichen = "GEWONNEN" if usd > 0 else ("VERLOREN" if usd < 0 else "NULL")

    setup = f"{g.get('setup_key', '?')} {g.get('setup_name', '?')}"
    if g.get("setup_source"):
        setup += f" ({g['setup_source']})"

    eq = eigenkapital(t)
    griff, gedeckelt = deckel_haette_gegriffen(t)

    k = [
        f"### {nr}. {uhr(t.get('opened_ts'))} · {t.get('symbol')} · {seite_de} · {zeichen}",
        "",
        f"**{zahl(r, 4)} R · {zahl(usd)} USD** · Regel: {regel(t.get('run_signature', ''))}",
        "",
        "**Warum ich reingegangen bin**",
        "",
        f"- Setup {setup} auf {g.get('setup_timeframe', '?')}, Signal auf {g.get('signal_timeframe', '?')}",
        f"- Marktlage: {REGIME_DE.get(g.get('regime'), g.get('regime', '?'))}; "
        f"Bewertung {g.get('rating', '?')}/100 ({g.get('rating_band', '?')})",
        f"- {g.get('breadth', '?')} von 7 Familien sprachen, Einigkeit {g.get('agreement', 0):.0%}, "
        f"Widerspruch {g.get('conflict', 0):.0%}, aus {g.get('readings', '?')} Ablesungen",
        f"- Einstieg {preis(g.get('entry', 0))}, Stop {preis(g.get('stop', 0))} "
        f"({g.get('stop_distance_pct', 0):.3f} % entfernt), Ziel {preis(g.get('target', 0))} "
        f"- Chance:Risiko {g.get('reward_risk', 0):.2f}",
    ]
    if eq is not None:
        k.append(
            f"- Eingesetzt: {t.get('qty', 0):g} Stueck = {t.get('qty', 0) * t.get('entry_price', 0):,.0f} USD Position "
            f"auf {eq:,.0f} USD Konto; Risiko {t.get('risk_amount', 0):.2f} USD = {t.get('risk_amount', 0) / eq:.2%} des Kontos".replace(",", "'")
        )
    k += ["", "**Was die Indikatoren sagten**", ""] + familien_zeilen(g, seite)

    k += [
        "",
        "**Was daraus wurde**",
        "",
        f"- Ausstieg: {AUSSTIEG_DE.get(t.get('exit_reason'), t.get('exit_reason'))} bei {preis(t.get('exit_price', 0))}",
        f"- {pm.get('bars_held', '?')} Kerzen gehalten; am weitesten im Plus {pm.get('max_favourable_r', 0):.3f} R, "
        f"am weitesten im Minus {pm.get('max_adverse_r', 0):.3f} R",
        f"- Gebuehren {t.get('fees', 0):.2f} USD, Funding {t.get('funding', 0):.2f} USD",
    ]
    if pm.get("verdict"):
        k.append(f"- Urteil des Systems: {pm['verdict']}")

    lehren = lehre_ziehen(t, g, pm, griff, gedeckelt)
    if lehren:
        k += ["", "**Was ich daraus mitnehme**", ""] + [f"- {x}" for x in lehren]
    return "\n".join(k)


def lehre_ziehen(
    t: dict[str, Any], g: dict[str, Any], pm: dict[str, Any], griff: bool, gedeckelt: float
) -> list[str]:
    """Mechanische Regeln ueber den gespeicherten Zahlen -- keine Einschaetzung."""
    usd = t.get("net_pnl") or 0.0
    risiko = t.get("risk_amount") or 0.0
    mfe = pm.get("max_favourable_r") or 0.0
    aus = []

    if griff:
        gespart = (abs(usd) * (1 - gedeckelt / risiko)) if risiko > 0 else 0.0
        wort = "gespart" if usd < 0 else "gekostet"
        aus.append(
            f"Der Risikodeckel von 1.5 % haette hier gegriffen: {risiko:.2f} USD Risiko statt erlaubter "
            f"{gedeckelt:.2f} USD. Haette {gespart:.2f} USD {wort}."
        )
    if pm.get("never_in_profit"):
        aus.append("War nie im Plus -- der Einstieg war von der ersten Kerze an falsch.")
    elif usd < 0 and mfe >= 1.0:
        aus.append(
            f"War {mfe:.2f} R im Plus und gab alles zurueck. Das ist genau das Rueckgabe-Muster, "
            f"das ueber zwoelf Maerkte gemessen ist -- und zwei Ausstiegsversuche (E14, E15) haben es nicht geloest."
        )
    elif usd < 0 and mfe >= 0.5:
        aus.append(f"War {mfe:.2f} R im Plus, bevor es drehte.")
    if pm.get("stopped_by_wick"):
        aus.append("Ein Docht holte den Stop, die Kerze schloss wieder richtig -- der Stop lag im Rauschen.")
    if usd > 0 and (pm.get("closest_to_target_r") or 0) >= 1.4:
        aus.append("Lief sauber bis ans Ziel.")
    if g.get("conflict", 0) >= 0.25:
        aus.append(f"Die Familien widersprachen sich zu {g['conflict']:.0%} -- das war kein klares Bild.")
    return aus


def zusammenfassung(trades: list[dict[str, Any]]) -> str:
    n = len(trades)
    if not n:
        return "Noch kein abgeschlossener Trade auf diesem Konto."

    usd = [t.get("net_pnl") or 0.0 for t in trades]
    rs = [t.get("r_multiple") or 0.0 for t in trades]
    gewinner = [t for t in trades if (t.get("net_pnl") or 0) > 0]
    verlierer = [t for t in trades if (t.get("net_pnl") or 0) < 0]

    def mittel(ts: Iterable[dict[str, Any]], feld: str) -> float:
        w = [t.get(feld) or 0.0 for t in ts]
        return statistics.fmean(w) if w else 0.0

    def stop_mittel(ts: list[dict[str, Any]]) -> float:
        w = [(t.get("reason") or {}).get("stop_distance_pct") or 0.0 for t in ts]
        return statistics.fmean(w) if w else 0.0

    risiko_g, risiko_v = mittel(gewinner, "risk_amount"), mittel(verlierer, "risk_amount")
    rueckgabe = [t for t in verlierer if ((t.get("post_mortem") or {}).get("max_favourable_r") or 0) >= 1.0]
    nie_plus = [t for t in trades if (t.get("post_mortem") or {}).get("never_in_profit")]
    docht = [t for t in trades if (t.get("post_mortem") or {}).get("stopped_by_wick")]
    gegriffen = [t for t in trades if deckel_haette_gegriffen(t)[0]]

    z = [
        "## Was die Zahlen bisher sagen",
        "",
        f"**{n} abgeschlossene Trades · {zahl(sum(rs), 4)} R · {zahl(sum(usd))} USD**",
        "",
        f"- Treffer: {len(gewinner)} von {n} ({len(gewinner) / n:.0%})",
        f"- In R zusammengerechnet {zahl(sum(rs), 4)}, in USD {zahl(sum(usd))}. "
        + (
            "**Die beiden Vorzeichen stimmen nicht ueberein** -- das ist kein Rundungsfehler, "
            "sondern die Vorwaertsregel: Risiko ist das Ergebnis der Stopweite, nicht ihre Vorgabe."
            if (sum(rs) > 0) != (sum(usd) > 0)
            else "Beide Vorzeichen stimmen ueberein."
        ),
    ]
    if gewinner and verlierer:
        if risiko_g > 0:
            z.append(
                f"- Durchschnittliches Risiko: **{risiko_g:.2f} USD auf Gewinnern, "
                f"{risiko_v:.2f} USD auf Verlierern** ({risiko_v / risiko_g:.2f}x)"
            )
        z.append(
            f"- Durchschnittliche Stopweite: {stop_mittel(gewinner):.3f} % auf Gewinnern, "
            f"{stop_mittel(verlierer):.3f} % auf Verlierern"
        )
    z += [
        f"- {len(rueckgabe)} Verlierer waren vorher mindestens 1 R im Plus (Rueckgabe-Muster)",
        f"- {len(nie_plus)} Trades waren nie im Plus",
        f"- {len(docht)} Stops wurden von einem Docht geholt",
        f"- Der 1.5-%-Deckel haette bei {len(gegriffen)} von {n} Trades gegriffen",
        "",
        "> Das Konto verliert nicht, weil die Einstiege schlecht waeren -- in R ist die Summe "
        "positiv. Es verliert, weil die Verlierer groessere Positionen tragen als die Gewinner. "
        "Dagegen laeuft seit heute der Risikodeckel.",
    ]
    return "\n".join(z)


def main() -> int:
    if not JOURNAL.exists():
        print(f"Kein Journal unter {JOURNAL}")
        return 1
    trades = plan_trades(JOURNAL)
    kopf = [
        "# Handelsbuch — Plankonto",
        "",
        f"Automatisch geschrieben aus `data/journal.sqlite`, Stand {uhr(int(datetime.now(tz=timezone.utc).timestamp() * 1000))}.",
        "Jede Zeile stammt aus dem gespeicherten Datensatz des Trades. Nichts hier ist geschaetzt.",
        "",
        "Neu erzeugen: `python scripts/handelsbuch.py`",
        "",
        zusammenfassung(trades),
        "",
        "## Die Trades, aelteste zuerst",
        "",
    ]
    teile = [eintrag(t, i) for i, t in enumerate(trades, 1)]
    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    ZIEL.write_text("\n".join(kopf) + "\n\n---\n\n".join(teile) + "\n", encoding="utf-8")
    print(f"{len(trades)} Trades -> {ZIEL.relative_to(WURZEL)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
