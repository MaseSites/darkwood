"""Regelpruefung des Chats: acht feste Regeln, ein Urteil.

Reine Funktion -- kein Sprachmodell, keine Datei, keine Uhr. Was Claude zu einem
Vorschlag schreibt, kommt hier nicht an: `pruefe` sieht nur Vorschlag, Lage und
Regelwerte. `unbekannt` zaehlt wie `verletzt`; angenommen ist ein Vorschlag nur,
wenn jede der acht Regeln `erfuellt` ist.
"""

from __future__ import annotations

from traidingbrain.api.chat.modelle import Lage, Regel, Regelwerte, Setup, Urteil, Vorschlag
from traidingbrain.api.terminal import KOSTEN_ROUNDTRIP, OrderWunsch
from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.enums import Timeframe
from traidingbrain.risk.limits import RiskLimits

#: `setups.timeframes: None` heisst "alle vier" Handelsebenen (M1 ist nur Simulator).
_ALLE_EBENEN = [Timeframe.M15.value, Timeframe.H1.value, Timeframe.H4.value, Timeframe.D1.value]
_LEER = "-"


def regelwerte_aus(config: AppConfig, plan: dict) -> Regelwerte:
    """Die Grenzen aus der laufenden Konfiguration und `config_offen/plan.yaml`."""
    setups = config.engine.setups
    ebenen = _ALLE_EBENEN if setups.timeframes is None else [t.value for t in setups.timeframes]
    return Regelwerte(
        require_agreement=setups.require_agreement,
        timeframes=ebenen,
        margin_share=float(plan["margin_share"]),
        leverage=float(plan["leverage"]),
        risk_cap_share=float(plan["risk_cap_share"]),
        max_cost_fraction=config.risk.limits.max_cost_fraction_of_risk,
        max_leverage=config.risk.leverage.max,
        kosten_roundtrip=KOSTEN_ROUNDTRIP,
    )


def _r(
    nr: int, name: str, status: str, wert: str, grenze: str, *, hinweis: str | None = None
) -> Regel:
    return Regel(nr=nr, name=name, status=status, wert=wert, grenze=grenze, hinweis=hinweis)


def _usd(x: float) -> str:
    return f"{x:,.2f} USD".replace(",", "'")


def _regel_1(
    side: str, preis: float | None, sl: float | None, tp: float | None, fehlt: str
) -> Regel:
    """Stop vorhanden, Stop und Ziel auf der richtigen Seite (wie `order_oeffnen`)."""
    lang = side == "long"
    grenze = f"Stop {'unter' if lang else 'über'} dem Kurs"
    if sl is None:
        return _r(
            1,
            "Stop und Ziel",
            "verletzt",
            "kein Stop",
            grenze,
            hinweis="Einen Stop angeben -- kein Setup liefert einen.",
        )
    if preis is None:
        return _r(1, "Stop und Ziel", "unbekannt", f"Stop {sl:g}", grenze, hinweis=fehlt)
    stop_ok = sl < preis if lang else sl > preis
    ziel_ok = tp is None or (tp > preis if lang else tp < preis)
    wert = f"Stop {sl:g}" + (f", Ziel {tp:g}" if tp is not None else "") + f" bei Kurs {preis:g}"
    if stop_ok and ziel_ok:
        return _r(1, "Stop und Ziel", "erfuellt", wert, grenze)
    falsch = "Stop" if not stop_ok else "Ziel"
    return _r(
        1,
        "Stop und Ziel",
        "verletzt",
        wert,
        grenze,
        hinweis=f"{falsch} liegt auf der falschen Seite des Kurses.",
    )


def _regel_2(side: str, bild: str | None, werte: Regelwerte) -> Regel:
    """Nicht gegen das Gesamtbild."""
    grenze = f"Bild = {side}"
    if not werte.require_agreement:
        return _r(2, "Gesamtbild", "erfuellt", bild or _LEER, "nicht verlangt")
    if bild is None:
        return _r(
            2, "Gesamtbild", "unbekannt", _LEER, grenze, hinweis="Gesamtbild nicht verfuegbar."
        )
    if bild == side:
        return _r(2, "Gesamtbild", "erfuellt", bild, grenze)
    hinweis = (
        "Gesamtbild ist neutral und stimmt damit nicht zu."
        if bild == "neutral"
        else f"Gesamtbild zeigt {bild} -- nur in Richtung des Bildes handeln."
    )
    return _r(2, "Gesamtbild", "verletzt", bild, grenze, hinweis=hinweis)


def _regel_3(
    side: str, setups: list[Setup] | None, folgt: bool, werte: Regelwerte, fehlt: str
) -> Regel:
    """Setup gleicher Richtung auf einer Handelsebene."""
    ebenen = ", ".join(werte.timeframes)
    grenze = f"{ebenen}, {side}"
    if not folgt:
        return _r(
            3, "Aktives Setup", "unbekannt", _LEER, grenze, hinweis="Markt wird nicht beobachtet"
        )
    if setups is None:
        return _r(3, "Aktives Setup", "unbekannt", _LEER, grenze, hinweis=fehlt)
    treffer = [
        s.timeframe for s in setups if s.side.lower() == side and s.timeframe in werte.timeframes
    ]
    if treffer:
        return _r(3, "Aktives Setup", "erfuellt", ", ".join(treffer), grenze)
    return _r(
        3,
        "Aktives Setup",
        "verletzt",
        "keines",
        grenze,
        hinweis=f"Warten, bis auf {ebenen} ein {side}-Setup aktiv ist.",
    )


def _limits_regeln(blockers: list[str], n_offen: int) -> list[Regel]:
    """Regel 6 und 7 aus `RiskLimits.check`: Positions-Blocker -> 6, alles andere -> 7."""
    deckel, bremsen = [], []
    for b in blockers:
        klein = b.lower()
        (bremsen if klein.startswith("kill switch") or "position" not in klein else deckel).append(
            b
        )
    raus = []
    for nr, name, blocker, wert, grenze, hinweis in (
        (
            6,
            "Positionsdeckel",
            deckel,
            f"{n_offen} offen",
            "offen, je Markt, je Richtung",
            "Erst eine offene Position schliessen.",
        ),
        (
            7,
            "Verlustbremsen",
            bremsen,
            "keine aktiv",
            "Tag, Woche, Pause nach Verlustserie",
            "Warten, bis die Bremse loest.",
        ),
    ):
        if blocker:
            raus.append(_r(nr, name, "verletzt", "; ".join(blocker), grenze, hinweis=hinweis))
        else:
            raus.append(_r(nr, name, "erfuellt", wert, grenze))
    return raus


def pruefe(v: Vorschlag, lage: Lage, werte: Regelwerte, limits: RiskLimits) -> Urteil:
    konto = lage.konto
    # Eine Lage fuer einen anderen Markt ist keine Grundlage: alles Marktbezogene unbekannt.
    passt = lage.symbol == v.symbol
    preis = lage.preis if passt else None
    bild = lage.bild if passt else None
    setups = lage.setups if (passt and lage.folgt) else None
    fehlt = "Daten fehlen" if passt else f"Lagebild gilt fuer {lage.symbol}, nicht {v.symbol}"

    # Fehlende Angaben: Planregel fuer Margin und Hebel, Stop aus dem Setup.
    margin = v.margin_usd if v.margin_usd is not None else werte.margin_share * konto.equity
    hebel = v.leverage if v.leverage is not None else werte.leverage
    sl, stop_vom_bot = v.sl, False
    if sl is None and setups:
        gleich = next((s for s in setups if s.side.lower() == v.side), None)
        if gleich is not None:
            sl, stop_vom_bot = gleich.stop, True

    regeln = [
        _regel_1(v.side, preis, sl, v.tp, "Kein aktueller Kurs" if passt else fehlt),
        _regel_2(v.side, bild, werte),
        _regel_3(v.side, setups, lage.folgt or not passt, werte, fehlt),
    ]

    # 4 -- Risiko je Trade; darueber wird die Margin gekuerzt, nicht abgelehnt.
    deckel = werte.risk_cap_share * konto.equity
    grenze = f"≤ {_usd(deckel)} ({werte.risk_cap_share:.1%})"
    risiko: float | None = None
    if preis is None or sl is None:
        regeln.append(
            _r(
                4,
                "Risiko je Trade",
                "unbekannt",
                _LEER,
                grenze,
                hinweis="Ohne Kurs und Stop kein Risiko.",
            )
        )
    elif margin <= 0 or deckel <= 0 or sl == preis:
        regeln.append(
            _r(
                4,
                "Risiko je Trade",
                "verletzt",
                _usd(margin),
                grenze,
                hinweis="Margin, Kontostand und Stop-Abstand muessen positiv sein.",
            )
        )
    else:
        risiko = abs(preis - sl) * margin * hebel / preis
        wert = _usd(risiko)
        if risiko > deckel:
            margin, risiko = margin * deckel / risiko, deckel
            wert = f"gekürzt auf {_usd(margin)} Margin"
        regeln.append(_r(4, "Risiko je Trade", "erfuellt", wert, grenze))

    # 5 -- Kosten im Verhaeltnis zum Risiko, ab hier mit der gekuerzten Margin.
    grenze = f"≤ {werte.max_cost_fraction:.0%} des Risikos"
    if risiko is None:
        regeln.append(
            _r(
                5,
                "Kosten zum Risiko",
                "unbekannt",
                _LEER,
                grenze,
                hinweis="Ohne Risiko keine Kostenquote.",
            )
        )
    else:
        kosten = margin * hebel * werte.kosten_roundtrip
        status = "erfuellt" if kosten <= werte.max_cost_fraction * risiko else "verletzt"
        regeln.append(
            _r(
                5,
                "Kosten zum Risiko",
                status,
                f"{_usd(kosten)} = {kosten / risiko:.1%}",
                grenze,
                hinweis=None
                if status == "erfuellt"
                else "Stop weiter weg setzen -- so eng frisst der Umlauf das Risiko.",
            )
        )

    # 6 und 7 -- dieselbe Pruefung wie beim Bot.
    blocker = limits.check(konto, symbol=v.symbol, side=v.side).blockers
    regeln += _limits_regeln(blocker, len(konto.open_positions))

    # 8 -- Hebel.
    ok = 1 <= hebel <= werte.max_leverage
    regeln.append(
        _r(
            8,
            "Hebel",
            "erfuellt" if ok else "verletzt",
            f"{hebel:g}x",
            f"1x bis {werte.max_leverage:g}x",
            hinweis=None if ok else f"Hebel auf hoechstens {werte.max_leverage:g}x setzen.",
        )
    )

    angenommen = all(r.status == "erfuellt" for r in regeln)
    order = (
        OrderWunsch(symbol=v.symbol, side=v.side, margin_usd=margin, leverage=hebel, tp=v.tp, sl=sl)
        if angenommen
        else None
    )
    return Urteil(
        angenommen=angenommen, regeln=regeln, order=order, stop_vom_bot=stop_vom_bot, preis=preis
    )
