"""Verdienen dieselben Maker-Konten durchgehend — oder wechseln die Gewinner?

**Die Frage, die E23 offen gelassen hat.** Dort stand: 60 % der Maker-Konten
waren im Plus. Das kann zweierlei heissen:

    ein Geschäftsmodell   dieselben Konten verdienen, Woche für Woche
    Glück                 jedes Fenster hat andere Gewinner, und 60 % ist
                          nur die Schiefe der Verteilung

Diese beiden sehen in einem Querschnitt **identisch** aus. Unterscheiden kann
sie nur, wer dasselbe Konto über zwei Fenster verfolgt.

**Gemessen wird der realisierte Spread, nicht das P&L.** Das P&L eines Kontos
über Stunden ist überwiegend die Kursbewegung auf seinem Bestand — in E23 auf
ETH 83 % davon. Wer darauf eine Beständigkeit misst, misst, ob dasselbe Konto
zweimal in dieselbe Richtung stand. Der realisierte Spread je Geschäft ist
richtungsbereinigt und misst das Handwerk.

**Die Null-Hypothese ist hier nicht „kein Zusammenhang".** Zwei Hälften
desselben Tages teilen sich Marktbedingungen; ein Konto, das in beiden
Hälften dieselbe Strategie fährt, korreliert schon deshalb. Darum steht neben
der Rangkorrelation eine **Mischprobe**: dieselben Geschäfte, den Konten
zufällig neu zugeteilt. Was darüber hinausgeht, ist Beständigkeit.

Aufruf:

    python scripts/study_lighter_persistenz.py
    python scripts/study_lighter_persistenz.py --markets BTC --horizont 60
"""

from __future__ import annotations

import argparse
import bisect
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STROM = ROOT / "data" / "quarantine" / "venue_ws"

#: Nach wie vielen Sekunden ein Maker-Geschäft nachbewertet wird.
#: 60 s ist der Horizont, auf dem E23 die adverse Selektion am klarsten sah.
HORIZONT = 60

#: Ab wie vielen Maker-Geschäften JE HÄLFTE ein Konto bewertet wird.
#:
#: Dreissig, weil ein realisierter Spread aus fünf Geschäften eine Zahl mit
#: einem Vertrauensbereich ist, der alles enthält. Die Schwelle kostet
#: Konten; eine niedrigere kostet die Aussage.
MIN_JE_HAELFTE = 30


def lade(markt: str) -> list[tuple[int, float, float, bool, int]]:
    """Alle Geschäfte: (ts, preis, usd, maker_verkauft, maker_konto)."""
    ordner = STROM / markt
    if not ordner.exists():
        return []
    raus = []
    for pfad in sorted(ordner.glob("strom-*.jsonl")):
        with pfad.open(encoding="utf-8", errors="replace") as f:
            for zeile in f:
                if '"typ":"trade"' not in zeile:
                    continue
                try:
                    nachricht = json.loads(zeile)["nachricht"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                for t in nachricht.get("trades") or []:
                    try:
                        ts = int(t["timestamp"])
                        preis = float(t["price"])
                        usd = float(t["usd_amount"])
                        maker_ist_ask = bool(t["is_maker_ask"])
                        konto = int(t["ask_account_id"] if maker_ist_ask
                                    else t["bid_account_id"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    raus.append((ts, preis, usd, maker_ist_ask, konto))
    raus.sort()
    return raus


def spread_je_konto(
    geschaefte: list, zeit: list[int], kurs: list[float], horizont: int,
) -> dict[int, tuple[float, float, int]]:
    """Je Konto: (gewichteter realisierter Spread in bp, Nominal, Geschäfte)."""
    summe: dict[int, float] = defaultdict(float)
    nominal: dict[int, float] = defaultdict(float)
    anzahl: dict[int, int] = defaultdict(int)
    for ts, preis, usd, maker_verkauft, konto in geschaefte:
        i = bisect.bisect_right(zeit, ts + horizont * 1000)
        if i >= len(kurs):
            continue
        p2 = kurs[i]
        rendite = (preis - p2) / preis if maker_verkauft else (p2 - preis) / preis
        summe[konto] += rendite * usd
        nominal[konto] += usd
        anzahl[konto] += 1
    return {k: (10_000 * summe[k] / nominal[k], nominal[k], anzahl[k])
            for k in summe if nominal[k] > 0}


def _rang(werte: list[float]) -> list[float]:
    """Ränge mit Mittelwert bei Gleichstand."""
    paare = sorted(range(len(werte)), key=lambda i: werte[i])
    r = [0.0] * len(werte)
    i = 0
    while i < len(paare):
        j = i
        while j + 1 < len(paare) and werte[paare[j + 1]] == werte[paare[i]]:
            j += 1
        mittel = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[paare[k]] = mittel
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> float:
    if len(a) < 3:
        return float("nan")
    ra, rb = _rang(a), _rang(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    oben = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    unten = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return oben / unten if unten else float("nan")


def _block(t: str) -> None:
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def untersuche(markt: str, horizont: int, min_je: int) -> None:
    alle = lade(markt)
    if len(alle) < 2000:
        print(f"  {markt}: zu wenige Geschäfte ({len(alle)}).")
        return

    zeit = [g[0] for g in alle]
    kurs = [g[1] for g in alle]
    mitte = zeit[len(zeit) // 2]
    erste = [g for g in alle if g[0] < mitte]
    zweite = [g for g in alle if g[0] >= mitte]

    # Die Kurszeitreihe bleibt die GANZE -- sonst fehlt der zweiten Hälfte
    # ihre Nachbewertung am Rand, und die ersten Geschäfte der zweiten
    # Hälfte würden gegen nichts bewertet.
    a = spread_je_konto(erste, zeit, kurs, horizont)
    b = spread_je_konto(zweite, zeit, kurs, horizont)

    gemeinsam = [k for k in a if k in b
                 and a[k][2] >= min_je and b[k][2] >= min_je]
    _block(f"{markt} — Beständigkeit des realisierten Spreads (+{horizont} s)")
    std = (zeit[-1] - zeit[0]) / 3_600_000
    print(f"  {len(alle):,} Geschäfte über {std:.1f} h, geteilt in der Mitte."
          .replace(",", "’"))
    print(f"  {len(gemeinsam)} Konten mit mindestens {min_je} Geschäften in BEIDEN Hälften.\n")
    if len(gemeinsam) < 8:
        print("  Zu wenige für eine Aussage.")
        return

    x = [a[k][0] for k in gemeinsam]
    y = [b[k][0] for k in gemeinsam]
    rho = spearman(x, y)

    # Die Mischprobe: dieselben Zahlen, die Zuordnung zerstoert. Sie sagt,
    # welche Korrelation allein aus der Verteilung faellt.
    import hashlib
    ordnung = sorted(range(len(y)),
                     key=lambda i: hashlib.sha256(str(gemeinsam[i]).encode()).hexdigest())
    rho_misch = spearman(x, [y[i] for i in ordnung])

    # Was dieser Test ueberhaupt aufloesen kann. Ohne diese Zahl ist ein
    # "nichts gefunden" nicht von einem "nicht hingeschaut" zu unterscheiden
    # -- und genau das ist der Fehler, den dieses Projekt am haeufigsten
    # findet. Der Standardfehler einer Rangkorrelation ist naeherungsweise
    # 1/sqrt(n-1).
    se = 1.0 / ((len(gemeinsam) - 1) ** 0.5)
    print(f"  Rangkorrelation Hälfte 1 → Hälfte 2:  {rho:+.4f}  ± {2*se:.4f} (2 SE)")
    print(f"  dieselbe Zahl nach Mischen:           {rho_misch:+.4f}")
    urteil = ("UNUNTERSCHEIDBAR von null" if abs(rho) < 2 * se
              else "ausserhalb des eigenen Fehlers")
    print(f"  → {urteil}. Dieser Test löst ab |ρ| > {2*se:.2f} auf;")
    print(f"    eine echte Beständigkeit darunter bliebe unsichtbar.")
    print()

    # Die Übergangstafel sagt mehr als eine Korrelation: sie zeigt, OB die
    # Guten gut bleiben, und nicht nur, dass es irgendeinen Zusammenhang gibt.
    median_a = statistics.median(x)
    median_b = statistics.median(y)
    oben_oben = sum(1 for i in range(len(x)) if x[i] > median_a and y[i] > median_b)
    oben_unten = sum(1 for i in range(len(x)) if x[i] > median_a and y[i] <= median_b)
    print(f"  Von den Konten über dem Median in Hälfte 1 ({oben_oben + oben_unten}):")
    anteil = oben_oben / (oben_oben + oben_unten) if (oben_oben + oben_unten) else 0
    gesamt_oben = oben_oben + oben_unten
    se_anteil = (0.25 / gesamt_oben) ** 0.5 if gesamt_oben else 0.0
    print(f"     {oben_oben} blieben darüber, {oben_unten} fielen darunter "
          f"= {anteil:.0%} ± {2*se_anteil:.0%}")
    print(f"     Bei reinem Zufall wären es 50 % — "
          + ("liegt im Fehler." if abs(anteil - 0.5) < 2 * se_anteil
             else "liegt ausserhalb."))

    posa = [k for k in gemeinsam if a[k][0] > 0]
    beide = [k for k in posa if b[k][0] > 0]
    if posa:
        print(f"\n  Konten mit POSITIVEM Spread in Hälfte 1: {len(posa)}")
        print(f"     davon auch in Hälfte 2 positiv: {len(beide)} = "
              f"{len(beide)/len(posa):.0%}")
        basis = sum(1 for k in gemeinsam if b[k][0] > 0) / len(gemeinsam)
        print(f"     Grundquote aller Konten in Hälfte 2: {basis:.0%}")
        print(f"     Unterschied: {len(beide)/len(posa) - basis:+.0%} Punkte")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", default="BTC,ETH,SOL")
    p.add_argument("--horizont", type=int, default=HORIZONT)
    p.add_argument("--min-je-haelfte", type=int, default=MIN_JE_HAELFTE)
    a = p.parse_args()

    for m in (x.strip().upper() for x in a.markets.split(",") if x.strip()):
        untersuche(m, a.horizont, a.min_je_haelfte)

    _block("WIE DAS ZU LESEN IST")
    print("""  Eine Rangkorrelation deutlich über der Mischprobe heisst: dasselbe
  Konto liefert in beiden Hälften ähnlich ab. Das ist das Muster eines
  Geschäftsmodells.

  Eine nahe der Mischprobe heisst: die Gewinner des einen Fensters sind
  nicht die des nächsten. Dann ist „60 % der Maker sind im Plus" die
  Schiefe einer Verteilung und keine Fähigkeit.

  Beides über ZWEI HÄLFTEN EINES TAGES. Zwei Hälften teilen sich
  Marktbedingungen, Teilnehmer und Volatilitätsregime -- sie sind die
  WOHLWOLLENDSTE Form dieser Prüfung. Was hier schon nicht besteht,
  besteht über eine Woche erst recht nicht.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
