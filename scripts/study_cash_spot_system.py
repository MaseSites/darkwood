"""Cash gegen Spot gegen das System — über dasselbe Fenster, bei gleichem Risiko.

**Warum diese Messung das Projekt abschliesst.** Der Beta-Befund sagt: Beta 1,0
zu BTC mit verlässlich negativem Residuum. Das heisst, das System fügt der
eingegangenen Marktrichtung keinen belegten Mehrwert hinzu und belastet sie mit
Kosten. Daraus folgt aber **nicht** automatisch „Spot halten" — Spot ist kein
nachgewiesener Weg zu 20x, sondern der einfachere und günstigere Ausdruck einer
*separaten* Beta-These. Ein fairer Vergleich braucht darum alle drei Arme
nebeneinander, über dasselbe Fenster und mit genannter Exposition.

So gefordert von der unabhängigen Prüfung am 18.10.2026, und als `E2.5`
(„Passives risikovergleichbares Exposure", Rolle: Kontrolle) schon im Register.

**Was dieser Vergleich NICHT kann, und das gehört vorne hin.** Die 7.335 Fills
sind in **zwölf getrennten** Läufen entstanden, jeder mit eigenen 1.000 USDT.
Es gibt keinen gemeinsamen Margin und keine geteilte Kasse — der gemeinsame
Portfoliomotor ist entworfen und nicht gebaut. Die Systemkurve ist darum
„zwölf unabhängige Konten", nicht „ein Konto über zwölf Märkte". Ein echtes
gepooltes Konto hätte weniger Trades (der Platzdeckel bindet) und wäre damit
*anders*, nicht nur skaliert.

**Und was „gleiches Risiko" hier heisst.** Drei Lesarten, alle drei
ausgegeben, weil sie verschiedene Fragen beantworten:

* *gleiche Nominale* — Spot voll investiert gegen das System wie gelaufen.
  Beantwortet: wer hat mehr verdient.
* *gleiche Schwankung* — die Spotposition auf die realisierte Tagesvolatilität
  des Systems skaliert. Beantwortet: wer hat je Risikoeinheit mehr verdient.
* *gleicher maximaler Rückgang* — die Spotposition so skaliert, dass ihr
  grösster Rückgang dem des Systems gleicht. Beantwortet: wer hat je
  ertragenem Schmerz mehr verdient.

    python scripts/study_cash_spot_system.py
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe

#: Risiko je Trade, wie `config/risk.yaml` es in `sizing` setzt. Nicht der
#: 3-%-Deckel: der ist die absolute Obergrenze und nur bei kalibrierter
#: Zuversicht ueberhaupt freigeschaltet.
RISIKO = 0.01

#: Handelstage je Jahr fuer die Annualisierung. Krypto handelt durchgehend.
TAGE_JAHR = 365.0

#: Unter so wenigen Tagen im Fenster ist eine Tagesvolatilitaet keine Zahl,
#: sondern Rauschen -- der Markt wird dann uebersprungen und das gesagt.
MIN_TAGE = 30


@dataclass(frozen=True, slots=True)
class Kurve:
    """Eine Kapitalkurve mit den drei Zahlen, die sie vergleichbar machen."""

    name: str
    endwert: float
    tagesvola: float
    max_rueckgang: float
    tage: float

    @property
    def jahresrendite(self) -> float:
        if self.tage <= 0 or self.endwert <= 0:
            return float("nan")
        return self.endwert ** (TAGE_JAHR / self.tage) - 1.0

    @property
    def rendite_je_vola(self) -> float:
        """Jahresrendite geteilt durch annualisierte Schwankung.

        Kein Sharpe: der risikofreie Satz ist nicht abgezogen, und das steht
        hier, damit die Zahl nicht als einer gelesen wird.
        """
        jahresvola = self.tagesvola * np.sqrt(TAGE_JAHR)
        return self.jahresrendite / jahresvola if jahresvola > 0 else float("nan")


def _rueckgang(kurve: np.ndarray) -> float:
    """Groesster Rueckgang vom Hoch, als Anteil."""
    if kurve.size == 0:
        return 0.0
    hoch = np.maximum.accumulate(kurve)
    return float(np.max(1.0 - kurve / hoch))


def system_kurve(r_werte: list[float], tage: float, name: str) -> Kurve:
    """Die R-Folge bei `RISIKO` je Trade zusammengesetzt.

    In Zeitordnung, nicht sortiert -- die Reihenfolge ist Teil des Ergebnisses,
    und sie zu mischen waere eine andere Behauptung.
    """
    schritte = 1.0 + RISIKO * np.array(r_werte, dtype=float)
    kurve = np.cumprod(schritte)
    # Die Schwankung je TAG, nicht je Trade: sonst waere sie nicht mit Spot
    # vergleichbar. Umgerechnet ueber die Trades pro Tag.
    je_trade = float(np.std(schritte - 1.0, ddof=1)) if len(schritte) > 1 else 0.0
    pro_tag = len(r_werte) / tage if tage > 0 else 0.0
    return Kurve(
        name=name,
        endwert=float(kurve[-1]) if kurve.size else 1.0,
        tagesvola=je_trade * np.sqrt(pro_tag),
        max_rueckgang=_rueckgang(kurve),
        tage=tage,
    )


def spot_kurve(closes: np.ndarray, *, hebel: float, name: str) -> Kurve:
    """Buy-and-hold auf dem Tagesschluss, optional skaliert.

    `hebel` ist keine Boersenhebelung, sondern der investierte Anteil: 1.0 ist
    voll investiert, 0.5 die Haelfte in Cash. Taeglich neu gewichtet, weil eine
    fixe Stueckzahl bei fallendem Kurs automatisch entschuldet und die
    Skalierung dann nicht mehr die wäre, die gemeint ist.
    """
    renditen = np.diff(closes) / closes[:-1]
    schritte = 1.0 + hebel * renditen
    if np.any(schritte <= 0):
        return Kurve(name=f"{name} (RUIN)", endwert=0.0, tagesvola=float("nan"),
                     max_rueckgang=1.0, tage=float(len(renditen)))
    kurve = np.cumprod(schritte)
    return Kurve(
        name=name,
        endwert=float(kurve[-1]),
        tagesvola=float(np.std(schritte - 1.0, ddof=1)) if len(schritte) > 1 else 0.0,
        max_rueckgang=_rueckgang(kurve),
        tage=float(len(renditen)),
    )


def _skaliere_auf(closes: np.ndarray, *, ziel: float, was: str) -> float:
    """Den investierten Anteil suchen, der Spot auf eine Zielgroesse bringt.

    Binaer, weil beide Zielgroessen monoton im Anteil sind und eine
    geschlossene Form fuer den maximalen Rueckgang nicht existiert.
    """
    tief, hoch = 0.0, 5.0
    for _ in range(60):
        mitte = (tief + hoch) / 2.0
        k = spot_kurve(closes, hebel=mitte, name="probe")
        wert = k.tagesvola if was == "vola" else k.max_rueckgang
        if not np.isfinite(wert) or wert > ziel:
            hoch = mitte
        else:
            tief = mitte
    return (tief + hoch) / 2.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    args = parser.parse_args(argv)

    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)

    zeilen: list[tuple[str, Kurve, Kurve, Kurve, Kurve]] = []
    alle_r: list[float] = []
    print("JE MARKT, ueber das Fenster des jeweiligen Replays\n")
    print(
        f"   {'Symbol':10s} {'Tage':>6s} {'n':>5s} | {'System':>9s} {'Spot':>9s} "
        f"{'Spot=Vola':>10s} {'Spot=DD':>9s} | {'Sys-DD':>7s} {'Spot-DD':>8s}"
    )

    for path in sorted(args.fills.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        symbol = str(blob["symbol"])
        fills = sorted(blob["fills"], key=lambda r: int(r["opened_ts"]))
        if not fills:
            continue
        r_werte = [float(r["r_multiple"]) for r in fills]
        alle_r.extend(r_werte)
        erst, letzt = int(blob["first_ts"]), int(blob["last_ts"])
        tage = (letzt - erst) / 86_400_000.0

        frame = store.read(symbol, Timeframe.D1)
        if frame.empty:
            print(f"   {symbol:10s} keine D1-Kerzen -- uebersprungen")
            continue
        fenster = frame[(frame["ts"] >= erst) & (frame["ts"] <= letzt)]
        closes = np.asarray(fenster["close"].to_numpy(), dtype=float)
        if closes.size < MIN_TAGE:
            print(f"   {symbol:10s} nur {closes.size} von {MIN_TAGE} Tagen -- uebersprungen")
            continue

        sys_k = system_kurve(r_werte, tage, "System")
        spot = spot_kurve(closes, hebel=1.0, name="Spot")
        auf_vola = spot_kurve(
            closes, hebel=_skaliere_auf(closes, ziel=sys_k.tagesvola, was="vola"),
            name="Spot=Vola",
        )
        auf_dd = spot_kurve(
            closes, hebel=_skaliere_auf(closes, ziel=sys_k.max_rueckgang, was="dd"),
            name="Spot=DD",
        )
        zeilen.append((symbol, sys_k, spot, auf_vola, auf_dd))
        print(
            f"   {symbol:10s} {tage:6.0f} {len(r_werte):5d} | "
            f"{sys_k.endwert:9.3f} {spot.endwert:9.3f} {auf_vola.endwert:10.3f} "
            f"{auf_dd.endwert:9.3f} | {sys_k.max_rueckgang:6.1%} "
            f"{spot.max_rueckgang:7.1%}"
        )

    if not zeilen:
        print("keine vergleichbaren Maerkte", flush=True)
        return 2

    print("\nGLEICHGEWICHTETES MITTEL UEBER DIE MAERKTE (Endwert als Faktor)")
    for i, name in ((1, "System, wie gelaufen"), (2, "Spot, voll investiert"),
                    (3, "Spot auf Systemvolatilitaet"), (4, "Spot auf Systemrueckgang")):
        werte = [z[i].endwert for z in zeilen]
        jahres = [z[i].jahresrendite for z in zeilen]
        rjv = [z[i].rendite_je_vola for z in zeilen if np.isfinite(z[i].rendite_je_vola)]
        print(
            f"   {name:30s} Endwert {statistics.fmean(werte):6.3f}x   "
            f"p.a. {statistics.fmean(jahres):+7.1%}   "
            f"Rendite/Vola {statistics.fmean(rjv):+6.2f}"
        )
    print(f"   {'Cash':30s} Endwert  1.000x   p.a.   +0.0%   Rendite/Vola    n/a")

    print("\nWIE OFT SCHLAEGT DAS SYSTEM DEN JEWEILIGEN ARM?")
    for i, name in ((2, "Spot voll"), (3, "Spot auf Vola"), (4, "Spot auf Rueckgang")):
        besser = sum(1 for z in zeilen if z[1].endwert > z[i].endwert)
        print(f"   gegen {name:22s} {besser:2d} von {len(zeilen)}")
    besser_cash = sum(1 for z in zeilen if z[1].endwert > 1.0)
    print(f"   gegen {'Cash':22s} {besser_cash:2d} von {len(zeilen)}")

    print(
        "\nLESEHILFE. 'Spot=Vola' und 'Spot=DD' sind KEINE handelbaren\n"
        "Strategien, sondern Normierungen: sie beantworten 'wer verdient mehr\n"
        "je Risikoeinheit', nicht 'was soll ich kaufen'. Und keiner der vier\n"
        "Arme ist ein Weg zu 20x in sechs Monaten -- die Marke dafuer ist\n"
        "+0.4536 R je Trade (scripts/goal_bar.py), und keiner erreicht sie.\n"
        "Der Vergleich entscheidet, welche BETA-THESE man ausdrueckt, nicht ob\n"
        "das Ziel erreichbar ist."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
