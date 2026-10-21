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
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from traidingbrain.journal.kontozusatz import regel_lang  # noqa: E402
from traidingbrain.journal.lehren import lehre_ziehen  # noqa: E402

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


MANUELL = WURZEL / "data" / "manual_paper.sqlite"


def manuelle_trades(pfad: Path) -> list[dict[str, Any]]:
    """Von Hand eroeffnete Trades, in dieselbe Form gebracht.

    **Warum sie hierhergehoeren.** Die Kontoansicht zaehlt sie mit, dieses
    Buch tat es nicht -- am 20.10.2026 meldete das Konto 13 Trades und das
    Buch 12, und die Differenz war genau ein Trade, den ein Mensch gemacht
    hat. Ein Buch, das eine Sorte Trade weglaesst, ist kein Buch.

    Sie tragen WENIGER als die des Bots: kein Setup, keine Familien, kein
    post_mortem. Das wird hier nicht erfunden -- es steht als Leerstelle da,
    und das ist die ehrliche Darstellung eines Trades ohne Plan.
    """
    if not pfad.exists():
        return []
    with sqlite3.connect(f"file:{pfad}?mode=ro", uri=True) as c:
        spalten = [d[1] for d in c.execute("PRAGMA table_info(positions)")]
        zeilen = [dict(zip(spalten, r, strict=False))
                  for r in c.execute("select * from positions where status='closed'")]
    raus = []
    for z in zeilen:
        einsatz = (z.get("qty") or 0) * (z.get("entry") or 0)
        raus.append({
            "symbol": z.get("symbol"), "opened_ts": z.get("opened_ts"),
            "closed_ts": z.get("closed_ts"), "entry_price": z.get("entry"),
            "exit_price": z.get("exit"), "qty": z.get("qty"),
            "leverage": z.get("leverage"), "net_pnl": z.get("pnl"),
            "fees": z.get("fees"), "funding": 0.0,
            "risk_amount": None, "r_multiple": None,
            "exit_reason": z.get("reason") or "manual",
            "run_signature": "|von Hand",
            "reason": {"side": z.get("side"), "entry": z.get("entry"),
                       "stop": z.get("sl"), "target": z.get("tp"), "families": []},
            "post_mortem": {},
            "_manuell": True, "_margin": z.get("margin"), "_einsatz": einsatz,
        })
    return raus


def regel(signatur: str) -> str:
    """`plan30x7r15f` -> '30 % x 7, Deckel 1.5 %, Verlustbremsen gelockert'.

    Zerlegt wird in `journal/kontozusatz.py` und NICHT hier. Diese Funktion
    hat es am 20.10.2026 selbst von Hand getan und ist an `float("15f")`
    gescheitert, als der Zusatz sein `f` bekam -- derselbe Bruch wie im
    Dashboard, zwei Stellen, ein Format.
    """
    return regel_lang(signatur)


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


def zahl(x: float | None, n: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+,.{n}f}".replace(",", "'")


def preis(x: float | None) -> str:
    """Leerstellen bleiben Leerstellen. Ein Trade von Hand hat keinen Stop und
    kein Ziel -- dort eine 0.00 zu drucken waere eine erfundene Zahl."""
    if x is None:
        return "—"
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
    r = t.get("r_multiple")
    usd = t.get("net_pnl") or 0.0
    zeichen = "GEWONNEN" if usd > 0 else ("VERLOREN" if usd < 0 else "NULL")

    if t.get("_manuell"):
        setup = "VON HAND -- kein Setup, keine Bewertung, keine Indikatorlage"
    else:
        setup = f"{g.get('setup_key', '?')} {g.get('setup_name', '?')}"
        if g.get("setup_source"):
            setup += f" ({g['setup_source']})"

    eq = eigenkapital(t)
    griff, gedeckelt = deckel_haette_gegriffen(t)

    k = [
        f"### {nr}. {uhr(t.get('opened_ts'))} · {t.get('symbol')} · {seite_de} · {zeichen}",
        "",
        f"**{zahl(r, 4) + ' R' if r is not None else 'kein R (ohne Stop)'} · {zahl(usd)} USD** · Regel: {regel(t.get('run_signature', ''))}",
        "",
        "**Warum ich reingegangen bin**",
        "",
        (f"- {setup}" if t.get("_manuell")
         else f"- Setup {setup} auf {g.get('setup_timeframe', '?')}, "
              f"Signal auf {g.get('signal_timeframe', '?')}"),
    ]
    if not t.get("_manuell"):
        k += [
            f"- Marktlage: {REGIME_DE.get(g.get('regime'), g.get('regime', '?'))}; "
            f"Bewertung {g.get('rating', '?')}/100 ({g.get('rating_band', '?')})",
            f"- {g.get('breadth', '?')} von 7 Familien sprachen, Einigkeit {g.get('agreement', 0):.0%}, "
            f"Widerspruch {g.get('conflict', 0):.0%}, aus {g.get('readings', '?')} Ablesungen",
            f"- Einstieg {preis(g.get('entry'))}, Stop {preis(g.get('stop'))} "
            f"({g.get('stop_distance_pct', 0):.3f} % entfernt), Ziel {preis(g.get('target'))} "
            f"- Chance:Risiko {g.get('reward_risk', 0):.2f}",
        ]
    else:
        k.append(f"- Einstieg {preis(g.get('entry'))}, Ausstieg {preis(t.get('exit_price'))}")
    risiko = t.get("risk_amount")
    if eq is not None and risiko is not None:
        k.append(
            f"- Eingesetzt: {t.get('qty', 0):g} Stueck = {t.get('qty', 0) * t.get('entry_price', 0):,.0f} USD Position "
            f"auf {eq:,.0f} USD Konto; Risiko {risiko:.2f} USD = {risiko / eq:.2%} des Kontos".replace(",", "'")
        )
    elif t.get("_manuell"):
        # Ohne Stop gibt es kein Risiko in R -- das ist keine fehlende Zahl,
        # sondern die Eigenschaft dieses Trades, und sie gehoert hingeschrieben.
        # Nur die ZAHLEN bekommen den Tausenderstrich. Ein .replace ueber den
        # ganzen Satz erwischt auch das Trennkomma -- "Position' Margin".
        def tsd(x: float) -> str:
            return f"{x:,.0f}".replace(",", "'")

        k.append(
            f"- Eingesetzt: {t.get('qty', 0):g} Stueck = {tsd(t.get('_einsatz') or 0)} USD Position, "
            f"Margin {tsd(t.get('_margin') or 0)} USD bei {t.get('leverage', 0):g}x"
        )
        k.append("- **Kein Stop und kein Ziel gesetzt.** Damit gibt es kein Risiko in R "
                 "und keine Chance:Risiko-Zahl -- der Trade hatte keine vorab "
                 "definierte Grenze, ab der er falsch gewesen waere.")
    if not t.get("_manuell"):
        k += ["", "**Was die Indikatoren sagten**", ""] + familien_zeilen(g, seite)

    k += [
        "",
        "**Was daraus wurde**",
        "",
        f"- Ausstieg: {AUSSTIEG_DE.get(t.get('exit_reason'), t.get('exit_reason'))} bei {preis(t.get('exit_price', 0))}",
        (f"- {pm.get('bars_held')} Kerzen gehalten; am weitesten im Plus "
         f"{pm.get('max_favourable_r', 0):.3f} R, am weitesten im Minus "
         f"{pm.get('max_adverse_r', 0):.3f} R" if pm.get("bars_held") is not None
         else f"- {(((t.get('closed_ts') or 0) - (t.get('opened_ts') or 0)) / 60000):.0f} Minuten gehalten; "
              "kein Verlaufsprotokoll, weil der Trade nicht ueber den Simulator lief"),
        f"- Gebuehren {t.get('fees', 0):.2f} USD, Funding {t.get('funding', 0):.2f} USD",
    ]
    if pm.get("verdict"):
        k.append(f"- Urteil des Systems: {pm['verdict']}")

    lehren = lehre_ziehen(t, g, pm, griff, gedeckelt)
    if lehren:
        k += ["", "**Was ich daraus mitnehme**", ""] + [f"- {x}" for x in lehren]
    return "\n".join(k)


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
    # Nur Trades mit mindestens einer beobachteten Kerze: `never_in_profit`
    # ist auch bei Trades unter einer Kerze Laenge wahr, dort ist es aber
    # "nicht beobachtet" und nicht "nie im Plus" (siehe journal/lehren.py).
    nie_plus = [
        t for t in trades
        if (t.get("post_mortem") or {}).get("never_in_profit")
        and ((t.get("post_mortem") or {}).get("bars_held") or 0) > 0
    ]
    unbeobachtet = [
        t for t in trades
        if (t.get("post_mortem") or {}).get("never_in_profit")
        and ((t.get("post_mortem") or {}).get("bars_held") or 0) == 0
    ]
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
        f"- {len(nie_plus)} Trades waren nie im Plus; bei {len(unbeobachtet)} weiteren ist es "
        f"nicht beobachtbar (kuerzer als eine Kerze)",
        f"- {len(docht)} Stops wurden von einem Docht geholt",
        f"- Der 1.5-%-Deckel haette bei {len(gegriffen)} von {n} Trades gegriffen",
        "",
    ]
    # Der Schlusssatz haengt vom Vorzeichen ab. Bis zum 21.10.2026 stand hier ein
    # fester Satz ("in R ist die Summe positiv"), der am Abend des 20.10. stimmte
    # und am naechsten Morgen bei -6.70 R weiter gedruckt wurde.
    if sum(rs) > 0 and sum(usd) < 0:
        z.append(
            "> Das Konto verliert nicht, weil die Einstiege schlecht waeren -- in R ist die Summe "
            "positiv. Es verliert, weil die Verlierer groessere Positionen tragen als die Gewinner. "
            "Dagegen laeuft der Risikodeckel von 1.5 %."
        )
    elif sum(rs) < 0:
        z.append(
            "> Das Konto verliert in R UND in USD: die Richtung der Einstiege stimmt in dieser "
            "Stichprobe nicht, nicht nur die Groesse. Ueber 7'335 Replay-Trades liegt die Erwartung "
            "je Trade in [-0.087, +0.059] R; diese Stichprobe ist zu klein, um etwas anderes zu belegen."
        )
    else:
        z.append("> Das Konto liegt in R und in USD im Plus. Bei dieser Stichprobengroesse ist das Rauschen.")
    return "\n".join(z)


def main() -> int:
    if not JOURNAL.exists():
        print(f"Kein Journal unter {JOURNAL}")
        return 1
    trades = plan_trades(JOURNAL) + manuelle_trades(MANUELL)
    trades.sort(key=lambda t: t.get("opened_ts") or 0)
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
