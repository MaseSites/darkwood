"""Was aus den eigenen Trades folgt — mechanisch, und mit dem Zweifel dabei.

**Der Anlass.** Der Auftrag lautete: „wenn du siehst, okay, ich habe dreimal mit
der gleichen Strategie verloren, dann merkst du vielleicht, dass diese Strategie
nicht das Gelbe vom Ei ist." Das ist genau die richtige Frage — und genau die
Stelle, an der ein Handelsjournal gefährlich wird.

Drei Verluste in Folge sind bei einer Strategie, die in Wahrheit eine Münze ist,
**jeder achte Fall**. Ein Journal, das daraufhin „Setup G funktioniert nicht"
schreibt, erfindet einen Befund aus Rauschen, und der nächste Schritt wäre, ein
funktionierendes Setup abzuschalten. Dieses Projekt hat genau diesen Fehler
schon einmal bezahlt: Setup F trug 54 % des gesamten Verlusts über 68 Trades,
und das dafür aufgesetzte Experiment E16 FIEL trotzdem (+0.0061 R, Intervall
über null) — F läuft weiter, weil 68 Trades nicht reichen.

Darum trägt jede Aussage hier die Zahl, die sie trägt, und den Zufall daneben:

    3 von 3 verloren   p = 12.5 %, wenn die Strategie eine Münze ist
    5 von 5 verloren   p =  3.1 %
    7 von 7 verloren   p =  0.8 %

Erst ab sieben wird es eng, und auch dann ist es eine Auffälligkeit und kein
Beweis — bei acht Setups über zwölf Märkte schaut man auf viele Serien, und
irgendeine ist immer die längste.

**Was dieses Modul NICHT tut.** Es schlägt keine Parameteränderung vor und
schaltet nichts ab. Eine gescheiterte Hypothese durch nachträgliche
Parameterauswahl zu retten ist die eine Sache, die hier nie passieren darf;
eine laufende durch eine Verlustserie abzuschalten ist dieselbe Sache mit
umgekehrtem Vorzeichen.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

#: Ab wie vielen Trades eine Setup-Zeile überhaupt eine Quote nennt.
#:
#: Unter fünf ist eine Trefferquote eine Aufzählung und keine Quote. Die
#: Zahlen stehen trotzdem da — nur ohne das Wort „Quote" darüber.
MIN_FUER_QUOTE = 5


class Muster(BaseModel):
    """Was ein Setup auf diesem Konto bisher getan hat."""

    setup: str
    name: str
    trades: int
    gewinner: int
    summe_usd: float
    summe_r: float
    mittel_r: float
    serie: int
    """Länge der aktuellen Serie. Negativ bei Verlusten, positiv bei Gewinnen."""

    zufall_pct: float | None
    """Wie wahrscheinlich diese Serie bei einer Münze wäre, in Prozent."""

    befund: str


class Lehre(BaseModel):
    trade_id: str
    symbol: str
    setup: str
    saetze: list[str]


def lehre_ziehen(
    t: dict[str, Any],
    g: dict[str, Any],
    pm: dict[str, Any],
    griff: bool = False,
    gedeckelt: float = 0.0,
) -> list[str]:
    """Mechanische Regeln über den gespeicherten Zahlen — keine Einschätzung.

    Jeder Satz hier ist aus einem Feld des Journals ableitbar. Keiner sagt,
    was als Nächstes zu tun ist: ein Journal, das aus einem Trade eine Regel
    macht, ist eine Optimierung auf eine Stichprobe der Grösse eins.
    """
    usd = t.get("net_pnl") or 0.0
    risiko = t.get("risk_amount") or 0.0
    mfe = pm.get("max_favourable_r") or 0.0
    aus: list[str] = []

    if griff and risiko > 0:
        gespart = abs(usd) * (1 - gedeckelt / risiko)
        wort = "gespart" if usd < 0 else "gekostet"
        aus.append(
            f"Der Risikodeckel von 1.5 % hätte hier gegriffen: {risiko:.2f} USD "
            f"Risiko statt erlaubter {gedeckelt:.2f} USD. Hätte {gespart:.2f} USD {wort}."
        )
    if pm.get("never_in_profit"):
        aus.append("War nie im Plus — der Einstieg war von der ersten Kerze an falsch.")
    elif usd < 0 and mfe >= 1.0:
        aus.append(
            f"War {mfe:.2f} R im Plus und gab alles zurück. Das ist das Rückgabe-Muster, "
            f"das über zwölf Märkte gemessen ist: der mittlere Trade erreicht +1.18 R "
            f"und endet bei -0.01 R. Zwei Ausstiegsversuche (E14, E15) haben es nicht "
            f"gelöst — ein Breakeven-Stop machte es messbar schlechter."
        )
    elif usd < 0 and mfe >= 0.5:
        aus.append(f"War {mfe:.2f} R im Plus, bevor es drehte.")
    if pm.get("stopped_by_wick"):
        aus.append(
            "Ein Docht holte den Stop, die Kerze schloss wieder richtig — der Stop "
            "lag im Rauschen. Das ist der häufigste Einzelfall: 51.9 % aller Stops."
        )
    if usd > 0 and (pm.get("closest_to_target_r") or 0) >= 1.4:
        aus.append("Lief sauber bis ans Ziel.")
    konflikt = g.get("conflict") or 0.0
    if konflikt >= 0.25:
        aus.append(f"Die Familien widersprachen sich zu {konflikt:.0%} — das war kein klares Bild.")
    return aus


def _zufall_pct(serie: int) -> float:
    """Wie wahrscheinlich eine Serie dieser Länge bei einer Münze ist, in Prozent."""
    n = abs(serie)
    return 100.0 * (0.5 ** n) if n else 100.0


def _befund(
    setup: str, n: int, gewinner: int, serie: int, mittel_r: float,
    rs: list[float] | None = None, summe_usd: float = 0.0,
) -> str:
    """Ein Satz über das Setup, der seine eigene Unsicherheit mitnennt."""
    if n < MIN_FUER_QUOTE:
        teil = f"{n} Trade{'s' if n != 1 else ''}, {gewinner} davon gewonnen"
        if serie <= -3:
            p = _zufall_pct(serie)
            return (
                f"{teil}. Aktuell {abs(serie)} Verluste in Folge — bei einer Strategie, "
                f"die in Wahrheit eine Münze ist, passiert das in {p:.1f} % der Fälle. "
                f"Das ist noch kein Befund."
            )
        return f"{teil}. Zu wenige, um irgendetwas zu sagen."

    quote = gewinner / n
    satz = f"{n} Trades, {quote:.0%} Treffer, {mittel_r:+.3f} R je Trade."
    if serie <= -3:
        p = _zufall_pct(serie)
        satz += (
            f" Aktuell {abs(serie)} Verluste in Folge (Zufall bei einer Münze: {p:.1f} %)."
        )
    elif serie >= 3:
        satz += f" Aktuell {serie} Gewinne in Folge."
    # Der Vergleich, der die Zahl einordnet. Hier stand zuerst „liegt
    # vollständig in dieser Spanne" -- und das war für Setup B mit +0.372 R
    # schlicht falsch, denn die Spanne endet bei +0.059. Gemeint war die
    # UNSICHERHEIT, also wird sie jetzt gerechnet statt behauptet.
    if rs and len(rs) > 1:
        mw = sum(rs) / len(rs)
        var = sum((x - mw) ** 2 for x in rs) / (len(rs) - 1)
        se = (var / len(rs)) ** 0.5
        lo, hi = mw - 2 * se, mw + 2 * se
        ueberlappt = lo <= 0.059 and hi >= -0.087
        satz += (
            f" Bei {n} Trades reicht die Unsicherheit von {lo:+.3f} bis {hi:+.3f} R "
            f"(zwei Standardfehler)"
            + (" und überlappt die gemessene Systemerwartung von -0.087 bis +0.059 R "
               "— dieser Wert ist von ihr nicht zu unterscheiden."
               if ueberlappt else
               " und liegt damit AUSSERHALB der gemessenen Systemerwartung von -0.087 "
               "bis +0.059 R. Das ist eine Auffälligkeit, kein Befund: bei acht Setups "
               "über zwölf Märkte ist irgendeines immer das auffälligste.")
        )

    # Der Widerspruch, der sonst unerklärt dasteht. R ist risikonormiert, USD
    # nicht -- ein positives Mittel in R bei einem Verlust in Geld heisst, dass
    # die Verlierer die GRÖSSEREN Positionen waren.
    if summe_usd < 0 < mittel_r:
        satz += (
            f" Achtung auf den Widerspruch: {mittel_r:+.3f} R im Mittel, aber "
            f"{summe_usd:.2f} USD. R ist auf das Risiko normiert, Geld nicht — "
            f"die Verlierer liefen hier auf grösseren Positionen als die Gewinner."
        )
    elif summe_usd > 0 > mittel_r:
        satz += (
            f" Umgekehrter Widerspruch: {mittel_r:+.3f} R im Mittel, aber "
            f"{summe_usd:+.2f} USD — die Gewinner liefen auf grösseren Positionen."
        )
    return satz


def muster(trades: list[dict[str, Any]]) -> list[Muster]:
    """Was jedes Setup bisher getan hat, nach Verlust sortiert.

    `trades` sind geschlossene Zeilen mit mindestens `setup`, `r_multiple`,
    `net_pnl` und `closed_ts`. Sortiert nach dem grössten Verlust zuerst: das
    ist die Zeile, die eine Frage aufwirft.
    """
    nach_setup: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        nach_setup.setdefault(str(t.get("setup") or "?"), []).append(t)

    raus: list[Muster] = []
    for setup, zeilen in nach_setup.items():
        zeilen.sort(key=lambda r: r.get("closed_ts") or 0)
        n = len(zeilen)
        gewinner = sum(1 for r in zeilen if (r.get("r_multiple") or 0) > 0)
        summe_usd = sum(r.get("net_pnl") or 0.0 for r in zeilen)
        summe_r = sum(r.get("r_multiple") or 0.0 for r in zeilen)

        # Die aktuelle Serie: vom jüngsten Trade rückwärts, solange das
        # Vorzeichen gleich bleibt.
        serie = 0
        for r in reversed(zeilen):
            gewann = (r.get("r_multiple") or 0) > 0
            if serie == 0:
                serie = 1 if gewann else -1
            elif (serie > 0) == gewann:
                serie += 1 if gewann else -1
            else:
                break

        mittel = summe_r / n if n else 0.0
        raus.append(Muster(
            setup=setup,
            name=str(zeilen[-1].get("setup_name") or setup),
            trades=n, gewinner=gewinner,
            summe_usd=round(summe_usd, 2), summe_r=round(summe_r, 3),
            mittel_r=round(mittel, 4), serie=serie,
            zufall_pct=round(_zufall_pct(serie), 2) if abs(serie) >= 3 else None,
            befund=_befund(setup, n, gewinner, serie, mittel,
                           rs=[r.get("r_multiple") or 0.0 for r in zeilen],
                           summe_usd=summe_usd),
        ))

    raus.sort(key=lambda m: m.summe_usd)
    return raus
