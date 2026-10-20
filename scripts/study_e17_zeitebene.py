"""E17 -- Die Zeitebene des Setups, auf 56 ungesehenen Maerkten.

===========================================================================
VORREGISTRIERUNG. Geschrieben am 20.10.2026, WAEHREND der Replay noch
rechnet und bevor eine einzige Zeile der ungesehenen Maerkte existiert.
Das ist der Punkt: die Tore unten koennen das Ergebnis nicht kennen.
===========================================================================

**Die Behauptung, die geprueft wird.** Aus den zwoelf gesehenen Maerkten
(7.335 Trades, Stand 11.10.) ergab sich ein geordneter Verlauf fuer Setup A
ueber die Zeitebenen -- D1 +0.1565 R, H4 +0.0682, H1 -0.0147, M15 -0.0774 --
und daraus der Kandidat "nur A auf D1+H4" mit +0.0856 R je Trade gegen
-0.0129 R der Basis. Das waere der erste positive Vorteil dieses Projekts.

Er ist IN-SAMPLE. Die Ebene wurde ausgewaehlt, NACHDEM die Tabelle gelesen
war. Genau dafuer gibt es ungesehene Maerkte.

**Warum beide Haelften neu gerechnet werden.** Die zwoelf gesehenen Fills
tragen `decision_version e218664b39c8`, der heutige Stand `0311ffba621b`.
Dazwischen liegt unter anderem die Korrektur des CRV-Tors, das vorher per
Gleitkomma entschied und Signale verwarf, die exakt auf der Schwelle lagen
(+16.2 % Trades). In-Sample von einem Codestand gegen Out-of-Sample vom
anderen zu halten, misst Code und Markt zugleich. Das Register verbietet es:
"Ein Ergebnis auf Daten unbekannter oder gemischter Herkunft ist keine
Messung." Beide Haelften kommen darum aus `data/replay_fills_0311/`.

**Was dieser Lauf NICHT beantwortet, und es steht im Register.** Er FILTERT
eine Trade-Liste. Setups konkurrieren aber um fuenf Plaetze, also haette ein
real beschraenkter Pool MEHR Trades als der gefilterte -- E16 hat gemessen,
dass beim Entfernen eines Setups mit 68 Trades sich 135 aenderten. Die
Filterung beantwortet "ist der Vorteil JE TRADE echt", nicht "wie viele
Trades gaebe es". Das ist zulaessig, weil die In-Sample-Zahl +0.0856 R
GENAUSO entstanden ist -- gefiltert gegen gefiltert ist derselbe Massstab.
Die Durchsatzfrage bleibt offen und wird hier nicht beantwortet.

---------------------------------------------------------------------------
DIE ARME, vorab und unveraenderlich
---------------------------------------------------------------------------
  E17.1   setup == "A"  UND  timeframe in {D1, H4}
  E17.2   timeframe != "M15"            (die untere Haelfte weggelassen)
  Basis   alle Trades                   (Vergleichsmassstab)

---------------------------------------------------------------------------
DIE TORE, vorab und unveraenderlich. BEIDE muessen fallen.
---------------------------------------------------------------------------
TOR 1 -- ABSOLUT PROFITABEL, nicht "besser als die Basis".
  Das zweiseitige Bonferroni-Intervall des Arms auf den UNGESEHENEN Maerkten
  liegt vollstaendig ueber null.
  Korrektur auf `total_comparisons: 73` des Registers: alpha = 0.05/73,
  z = 3.396. Nicht auf die zwei Zellen dieses Arms -- die 73 ist die Zahl,
  die das Register fuehrt, und sie steht dort nur an einer Stelle, damit sie
  nicht driftet.
  Geclustert ZWEIWEGIG nach Markt UND 7-Tage-Block (Cameron/Gelbach/Miller,
  V = V_markt + V_zeit - V_schnitt). Nur nach Markt zu clustern erfasst
  gemessen 0.682 der wahren Streuung; ein gemeinsamer Wochenfaktor traegt
  96.9 % der Struktur.
  BEGRUENDUNG, dass "absolut" und nicht "gegen die Basis" geprueft wird:
  der Champion dieses Projekts ist mit -0.0340 R negativ. Ein kleinerer
  Verlust ist kein Gewinn.

TOR 2 -- WIEDERHOLUNG.
  unseen_mittel / seen_mittel liegt in [0.5, 2.0], beide aus
  `replay_fills_0311`. Das Band wird nach Kenntnis des Ergebnisses NICHT
  geaendert. Ein Vorzeichenwechsel faellt immer, egal wie das Verhaeltnis
  ausfaellt.

ABBRUCH statt Urteil:
  Hat ein Arm auf den ungesehenen Maerkten weniger als 200 Trades, lautet das
  Ergebnis UNENTSCHEIDBAR und nicht "gefallen". Eine Stichprobe, die zu klein
  ist, hat nichts widerlegt.

---------------------------------------------------------------------------
DER SCHWANZ, vorab erklaert
---------------------------------------------------------------------------
Berichtet werden IMMER, auch wenn die Tore fallen: schlechtester
7-Tage-Block, schlechtester Markt, groesster Rueckgang in R, und der Anteil
der Maerkte mit negativem Mittel. E10 hat einen Mittelwert verbessert und
dabei den groessten Einzelverlust verdreifacht; seitdem werden
Schwanzgroessen VOR dem Lauf erklaert.

    python scripts/study_e17_zeitebene.py
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
NEU = ROOT / "data" / "replay_fills_0311"
ALT = ROOT / "data" / "replay_fills"

TAG_MS = 86_400_000
#: Aus `audit/EXPERIMENTS_NEXT.yaml: total_comparisons`. Wird beim Lauf
#: gegen die Datei geprueft, damit die Zahl nicht still auseinanderlaeuft.
VERGLEICHE = 73
#: Unter so vielen Trades wird nicht geurteilt, sondern abgebrochen.
MIN_TRADES = 200
#: Das Wiederholungsband. Steht hier und wird nicht nachtraeglich bewegt.
BAND = (0.5, 2.0)

OBERE = ("D1", "H4")


def kennbuchstabe(setup: str) -> str:
    """Aus "A Momentum-Breakout (V08)" wird "A".

    Das Feld `setup` traegt den vollen Namen, nicht den Buchstaben. Ein
    Vergleich `setup == "A"` trifft darum NICHTS -- und das faellt nicht auf,
    weil ein leerer Arm wie ein ehrliches "unentscheidbar" aussieht statt wie
    ein Fehler. Gefunden, weil die beiden anderen Arme gegen die bekannten
    Registerzahlen geprueft wurden und dieser keine Zahl lieferte.

    `split()[0]` und nicht `startswith("A")`: der Praefix ist ein eigenes
    Wort, und ein Setup, das spaeter "AB ..." hiesse, wuerde sonst mitgezaehlt.
    """
    return setup.split()[0] if setup else ""


@dataclass(frozen=True, slots=True)
class Arm:
    id: str
    name: str
    passt: object  # Callable[[dict], bool]


ARME = (
    Arm("E17.1", "nur A auf D1+H4",
        lambda z: kennbuchstabe(z["setup"]) == "A" and z["timeframe"] in OBERE),
    Arm("E17.2", "alles ohne M15",
        lambda z: z["timeframe"] != "M15"),
    Arm("Basis", "alle Trades", lambda z: True),
)


def lade(wurzel: pathlib.Path) -> list[dict]:
    zeilen: list[dict] = []
    for pfad in sorted(wurzel.glob("*.json")):
        blob = json.loads(pfad.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            zeilen.append({
                "symbol": blob["symbol"],
                "ts": int(row["opened_ts"]),
                "r": float(row["r_multiple"]),
                "setup": str(row.get("setup") or ""),
                "timeframe": str(row.get("timeframe") or ""),
                "stand": str(blob.get("decision_version") or "?"),
            })
    zeilen.sort(key=lambda z: z["ts"])
    return zeilen


def _v(e: np.ndarray, gruppen: np.ndarray, n: int) -> float:
    return float(sum(e[gruppen == g].sum() ** 2 for g in set(gruppen.tolist()))) / (n * n)


def zweiweg(werte: np.ndarray, markt: np.ndarray, zeit: np.ndarray,
            z_krit: float) -> tuple[float, float, float]:
    """Mittel und zweiwegig geclustertes Intervall. NaN, wenn nicht bildbar."""
    n = werte.size
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    e = werte - werte.mean()
    schnitt = np.array([f"{a}|{b}" for a, b in zip(markt, zeit, strict=True)])
    var = _v(e, markt, n) + _v(e, zeit, n) - _v(e, schnitt, n)
    if var <= 0:
        return float(werte.mean()), float("nan"), float("nan")
    se = math.sqrt(var)
    m = float(werte.mean())
    return m, m - z_krit * se, m + z_krit * se


def schwanz(zeilen: list[dict]) -> dict:
    """Vorab erklaert: schlechtester Block, schlechtester Markt, Rueckgang."""
    if not zeilen:
        return {}
    r = np.array([z["r"] for z in zeilen])
    ts = np.array([z["ts"] for z in zeilen])
    sym = np.array([z["symbol"] for z in zeilen])
    bl = ((ts - ts.min()) // (7 * TAG_MS)).astype(int)
    je_block = {b: r[bl == b].mean() for b in set(bl.tolist())}
    je_markt = {s: r[sym == s].mean() for s in set(sym.tolist())}
    kurve = np.cumsum(r)
    rueckgang = float((np.maximum.accumulate(kurve) - kurve).max()) if r.size else 0.0
    return {
        "schlechtester_block": min(je_block.values()),
        "schlechtester_markt": min(je_markt, key=je_markt.get),
        "schlechtester_markt_r": min(je_markt.values()),
        "groesster_rueckgang_R": rueckgang,
        "anteil_maerkte_negativ": sum(1 for v in je_markt.values() if v < 0) / len(je_markt),
        "maerkte": len(je_markt),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fills", type=pathlib.Path, default=NEU)
    a = p.parse_args(argv)

    if not a.fills.exists():
        print(f"  {a.fills} fehlt. Der Replay laeuft noch?")
        return 2

    gesehen_syms = {q.stem for q in ALT.glob("*.json")}
    alle = lade(a.fills)
    if not alle:
        print("  Keine Fills. Der Replay laeuft noch?")
        return 2

    staende = {z["stand"] for z in alle}
    print("=" * 76)
    print("E17 -- Die Zeitebene des Setups, auf ungesehenen Maerkten")
    print("=" * 76)
    print(f"\n  Quelle        {a.fills}")
    print(f"  Codestaende   {sorted(staende)}")
    if len(staende) > 1:
        print("\n  ABBRUCH: mehr als ein Entscheidungscode in der Stichprobe.")
        print("  Ein Ergebnis auf gemischter Herkunft ist keine Messung.")
        return 3

    gesehen = [z for z in alle if z["symbol"] in gesehen_syms]
    unseen = [z for z in alle if z["symbol"] not in gesehen_syms]
    n_s = len({z["symbol"] for z in gesehen})
    n_u = len({z["symbol"] for z in unseen})
    print(f"  Gesehen       {n_s} Maerkte, {len(gesehen):,} Trades")
    print(f"  Ungesehen     {n_u} Maerkte, {len(unseen):,} Trades")

    z_krit = NormalDist().inv_cdf(1 - 0.05 / (2 * VERGLEICHE))
    print(f"\n  Bonferroni ueber {VERGLEICHE} Vergleiche: z = {z_krit:.3f} statt 1.960")
    print(f"  Wiederholungsband {BAND[0]}-{BAND[1]}x, Mindestzahl {MIN_TRADES} Trades")

    ergebnis = []
    for arm in ARME:
        u = [z for z in unseen if arm.passt(z)]
        s = [z for z in gesehen if arm.passt(z)]
        print("\n" + "-" * 76)
        print(f"  {arm.id}  {arm.name}")
        print(f"    ungesehen {len(u):,} Trades ({len(u)/max(1,len(unseen))*100:.1f} %)"
              f"   gesehen {len(s):,} Trades")

        if not u:
            print("    UNENTSCHEIDBAR: keine Trades.")
            ergebnis.append({"arm": arm.id, "urteil": "unentscheidbar"})
            continue

        ur = np.array([z["r"] for z in u])
        um = np.array([z["symbol"] for z in u])
        ut = ((np.array([z["ts"] for z in u]) - min(z["ts"] for z in u)) // (7 * TAG_MS)).astype(int)
        mittel, lo, hi = zweiweg(ur, um, ut.astype(str), z_krit)
        s_mittel = float(np.mean([z["r"] for z in s])) if s else float("nan")

        print(f"    UNGESEHEN  {mittel:+.4f} R  [{lo:+.4f}, {hi:+.4f}]")
        print(f"    GESEHEN    {s_mittel:+.4f} R  (derselbe Codestand)")

        if len(u) < MIN_TRADES:
            print(f"    UNENTSCHEIDBAR: unter {MIN_TRADES} Trades.")
            ergebnis.append({"arm": arm.id, "urteil": "unentscheidbar", "n": len(u)})
            continue

        tor1 = bool(lo == lo and lo > 0)      # NaN-sicher
        verh = mittel / s_mittel if s_mittel not in (0.0,) and s_mittel == s_mittel else float("nan")
        gleiches_vz = (mittel > 0) == (s_mittel > 0)
        tor2 = bool(gleiches_vz and verh == verh and BAND[0] <= verh <= BAND[1])

        print(f"    TOR 1 (Intervall ganz ueber null)   {'BESTANDEN' if tor1 else 'GEFALLEN'}")
        print(f"    TOR 2 (Wiederholung {BAND[0]}-{BAND[1]}x)        "
              f"{'BESTANDEN' if tor2 else 'GEFALLEN'}  (Verhaeltnis {verh:.2f}x)")

        t = schwanz(u)
        print(f"    SCHWANZ    schlechtester Block {t['schlechtester_block']:+.4f} R"
              f" | schlechtester Markt {t['schlechtester_markt']} {t['schlechtester_markt_r']:+.4f} R")
        print(f"               groesster Rueckgang {t['groesster_rueckgang_R']:.1f} R"
              f" | {t['anteil_maerkte_negativ']*100:.0f} % der {t['maerkte']} Maerkte negativ")

        urteil = "BESTEHT" if (tor1 and tor2) else "GEFALLEN"
        if arm.id != "Basis":
            print(f"    >>> {arm.id}: {urteil}")
        ergebnis.append({
            "arm": arm.id, "n": len(u), "mittel": mittel, "lo": lo, "hi": hi,
            "gesehen": s_mittel, "verhaeltnis": verh,
            "tor1": tor1, "tor2": tor2, "urteil": urteil, "schwanz": t,
        })

    ziel = ROOT / "audit" / "E17_ERGEBNIS.json"
    ziel.write_text(json.dumps({
        "vergleiche": VERGLEICHE, "z": z_krit, "band": BAND,
        "min_trades": MIN_TRADES, "codestand": sorted(staende),
        "maerkte_gesehen": n_s, "maerkte_ungesehen": n_u,
        "arme": ergebnis,
    }, indent=2, default=float), encoding="utf-8")
    print(f"\n  Geschrieben: {ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
