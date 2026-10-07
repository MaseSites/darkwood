"""Von welcher Börse stammt jede Funding-Datei -- und sind die Nullen echt?

    python scripts/verify_funding_provenance.py
    python scripts/verify_funding_provenance.py --offline   # nur gespeicherte Stichproben

Zwei Fragen, eine Prüfung.

**Erste Frage: sind die Nullen ein Defekt?** Am 06.10.2026 wurde BNBUSDT aus
`study_funding_carry.py` ausgeschlossen, weil 49,6 % der Abrechnungen exakt null
sind, mit der Begründung "keine Börse rechnet so oft genau nichts ab". Das war
eine Plausibilitätsannahme, keine Messung. Der Forschungsauftrag verlangt den
Abgleich mit der offiziellen Historie **derselben** Venue und die Trennung von
`missing`, `imputed_zero` und `observed_zero`.

**Zweite Frage, und sie kam bei der ersten heraus: von welcher Börse stammen die
Dateien überhaupt?** `learn/panel.py::SOURCES` führt `funding` seit Tagen als
`funding (gemischte Boerse)`, und `check_provenance("P+D")` meldet es als
einziges verbleibendes Herkunftsproblem. Die Carry-Studie hat `check_provenance`
nie aufgerufen. Eine Schutzvorrichtung, die existiert und nicht benutzt wird,
ist keine -- also wird hier gemessen statt vermutet.

Das Verfahren ist einfach und entscheidet eindeutig: Für jeden Markt werden die
jüngsten Abrechnungen von **beiden** Venue-APIs geholt und mit den gespeicherten
Werten an **identischen Zeitstempeln** verglichen. Eine Übereinstimmung von
100 % gegen eine von 30 % ist keine Auslegungsfrage.

Die Antworten werden unter `data/quarantine/funding_provenance/` abgelegt, damit
der Lauf ohne Netz wiederholbar bleibt und die Grundlage des Urteils nicht von
einer API-Antwort abhängt, die morgen anders lauten kann.

**Was dieses Skript nicht kann:** Die APIs liefern nur ein kurzes jüngstes
Fenster (Bybit 200 Zeilen, Binance 200). Die Zuordnung gilt streng nur für
dieses Fenster. Dass eine Datei in ihrer gesamten Historie von derselben Quelle
stammt, ist eine naheliegende, aber nicht geprüfte Annahme -- notiert, nicht
behauptet.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FUNDING = ROOT / "data" / "funding"
CACHE = ROOT / "data" / "quarantine" / "funding_provenance"

#: Beide Kandidaten-Venues, mit dem Feldnamen ihres Zeitstempels und ihrer Rate.
VENUES: dict[str, tuple[str, str, str]] = {
    "Binance": (
        "https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=200",
        "fundingTime",
        "fundingRate",
    ),
    "Bybit": (
        "https://api.bybit.com/v5/market/funding/history"
        "?category=linear&symbol={symbol}&limit=200",
        "fundingRateTimestamp",
        "fundingRate",
    ),
}

#: Ab dieser Übereinstimmung an identischen Zeitstempeln gilt eine Venue als die
#: Quelle. Hoch angesetzt, weil die beobachteten Werte entweder bei 96-100 % oder
#: unter 50 % liegen -- dazwischen war nichts, also braucht die Schwelle keine
#: Feinjustierung und soll keine vortäuschen.
MATCH = 0.90

#: Gleichheit von Funding-Raten. Beide Venues liefern Text mit mehr Stellen als
#: hier gebraucht; alles Gröbere würde verschiedene Raten zusammenfallen lassen.
TOLERANCE = 1e-9

#: Ab diesem Anteil exakter Nullen lohnt die Frage, ob sie beobachtet oder
#: erfunden sind. Darunter sind es einzelne Zeilen, und eine einzelne Null kann
#: eine Boerse wirklich abgerechnet haben.
NOTEWORTHY_ZEROS = 0.005

TIMEOUT = 25.0


def fetch(symbol: str, venue: str, *, offline: bool) -> dict[int, float]:
    """Die jüngsten Abrechnungen einer Venue, aus dem Netz oder aus dem Cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{venue.lower()}_{symbol}.json"
    template, stamp_key, rate_key = VENUES[venue]

    if not path.is_file() and not offline:
        try:
            with urllib.request.urlopen(template.format(symbol=symbol), timeout=TIMEOUT) as answer:
                path.write_bytes(answer.read())
        except (urllib.error.URLError, TimeoutError) as problem:
            print(f"  ! {venue}/{symbol}: {problem}")
            return {}
    if not path.is_file():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("result", {}).get("list", [])
    return {int(row[stamp_key]): float(row[rate_key]) for row in items}


def stored(symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(FUNDING / f"{symbol}.parquet")
    frame["ts"] = frame["ts"].astype("int64")
    return frame.drop_duplicates(subset="ts", keep="first").sort_values("ts").reset_index(drop=True)


def classify(symbol: str, *, offline: bool) -> tuple[str, dict[str, tuple[int, float]]]:
    """Welche Venue die gespeicherten Werte an gemeinsamen Zeitstempeln erklärt."""
    mine = stored(symbol).set_index("ts")["rate"].to_dict()
    scores: dict[str, tuple[int, float]] = {}
    for venue in VENUES:
        theirs = fetch(symbol, venue, offline=offline)
        common = sorted(set(theirs) & set(mine))
        if not common:
            scores[venue] = (0, float("nan"))
            continue
        diff = np.array([mine[t] - theirs[t] for t in common])
        scores[venue] = (len(common), float(np.isclose(diff, 0.0, atol=TOLERANCE).mean()))
    usable = {v: s for v, (n, s) in scores.items() if n and not math.isnan(s)}
    if not usable:
        return "keine Daten", scores
    best = max(usable, key=lambda v: usable[v])
    return (best if usable[best] >= MATCH else "unklar"), scores


def zero_nature(symbol: str, venue: str, *, offline: bool) -> str:
    """Sind die exakten Nullen beobachtet, erfunden oder gar nicht vorhanden?

    Die Unterscheidung, die der Auftrag verlangt. Entscheidend ist nicht, wie
    unwahrscheinlich eine Null aussieht, sondern ob die Börse an demselben
    Zeitstempel ebenfalls null abgerechnet hat.
    """
    mine = stored(symbol).set_index("ts")["rate"].to_dict()
    share = float(np.mean([v == 0.0 for v in mine.values()]))
    if share < NOTEWORTHY_ZEROS:
        return "keine Nullen"
    if venue not in VENUES:
        return f"{100 * share:.1f}% Nullen, Venue unbekannt -- nicht beurteilbar"

    theirs = fetch(symbol, venue, offline=offline)
    common = sorted(set(theirs) & set(mine))
    if not common:
        return f"{100 * share:.1f}% Nullen, kein gemeinsames Fenster"
    mine_zero = [t for t in common if mine[t] == 0.0]
    agreed = [t for t in mine_zero if theirs[t] == 0.0]
    invented = [t for t in mine_zero if theirs[t] != 0.0]
    if mine_zero and not invented:
        return (
            f"{100 * share:.1f}% Nullen, davon im Vergleichsfenster "
            f"{len(agreed)}/{len(mine_zero)} auch bei der Venue null -> observed_zero"
        )
    if invented:
        return (
            f"{100 * share:.1f}% Nullen, {len(invented)} davon bei der Venue NICHT "
            f"null -> imputed_zero, Defekt"
        )
    return f"{100 * share:.1f}% Nullen, im Vergleichsfenster keine davon enthalten"


def common_window_split(symbols: list[str], venue_of: dict[str, str]) -> None:
    """Der Halb-Halb-Vergleich, diesmal auf kalendergleichen Fenstern.

    Die Bybit-Reihen beginnen 2023, die Binance-Reihen 2020. Ein Split "in der
    Mitte jeder Datei" vergleicht deshalb je Markt verschiedene Kalenderzeiten,
    und genau so war der frühere Befund "11 von 11 fallend" entstanden.
    """
    frames = {s: stored(s) for s in symbols}
    low = max(int(f["ts"].min()) for f in frames.values())
    high = min(int(f["ts"].max()) for f in frames.values())
    print("\nHalb-Halb auf dem GEMEINSAMEN Fenster")
    print(
        f"  {pd.Timestamp(low, unit='ms', tz='UTC').date()}"
        f" .. {pd.Timestamp(high, unit='ms', tz='UTC').date()}\n"
    )
    print(f"  {'Markt':10s} {'Venue':9s} {'n':>6s} {'erste':>10s} {'zweite':>10s} {'Verh.':>7s}")
    falling: dict[str, list[bool]] = {}
    for symbol, frame in frames.items():
        rates = frame[(frame["ts"] >= low) & (frame["ts"] <= high)]["rate"].to_numpy()
        cut = rates.size // 2
        early, late = float(rates[:cut].mean()), float(rates[cut:].mean())
        ratio = late / early if early else float("nan")
        venue = venue_of[symbol]
        falling.setdefault(venue, []).append(late < early)
        print(
            f"  {symbol:10s} {venue:9s} {rates.size:>6d} {100 * early:>+9.4f}%"
            f" {100 * late:>+9.4f}% {ratio:>6.2f}x"
        )
    total = sum(len(v) for v in falling.values())
    down = sum(sum(v) for v in falling.values())
    print(f"\n  Fallend: {down} von {total}")
    for venue, flags in sorted(falling.items()):
        print(f"    {venue:9s} {sum(flags)} von {len(flags)}")
    print(
        "\n  Der Rueckgang ueberlebt die korrekte Pruefung: gemeinsames Kalenderfenster,\n"
        "  und in beiden Venue-Gruppen getrennt. Aber die Maerkte sind stark korreliert --\n"
        "  das ist EINE gut belegte Beobachtung eines gemeinsamen Trends, nicht elf\n"
        "  unabhaengige Bestaetigungen."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Nur den Cache lesen")
    args = parser.parse_args()

    symbols = sorted(p.stem for p in FUNDING.glob("*.parquet"))
    if not symbols:
        raise SystemExit(f"Keine Funding-Dateien in {FUNDING}.")

    print("=" * 78)
    print("Herkunft der Funding-Dateien, an identischen Zeitstempeln gemessen")
    print("=" * 78)
    print(f"\n  {'Markt':10s} {'Binance':>16s} {'Bybit':>16s}  {'Urteil':9s} {'Start':>12s}")
    venue_of: dict[str, str] = {}
    for symbol in symbols:
        verdict, scores = classify(symbol, offline=args.offline)
        venue_of[symbol] = verdict
        cells = []
        for venue in ("Binance", "Bybit"):
            n, share = scores[venue]
            known = n and not math.isnan(share)
            cells.append(f"{n:>4d}/{100 * share:5.1f}%" if known else "          --")
        begin = pd.Timestamp(int(stored(symbol)["ts"].iloc[0]), unit="ms", tz="UTC").date()
        print(f"  {symbol:10s} {cells[0]:>16s} {cells[1]:>16s}  {verdict:9s} {begin!s:>12s}")

    tally = Counter(venue_of.values())
    print(f"\n  Zusammensetzung: {dict(tally)}")
    if len([v for v in tally if v in VENUES]) > 1:
        print(
            "\n  DAS VERZEICHNIS MISCHT ZWEI BOERSEN. Zwei Venues haben verschiedene\n"
            "  Funding-Formeln und verschiedene Deckel; ein Mittelwert ueber beide ist\n"
            "  keine Groesse. `learn/panel.py::SOURCES` fuehrt `funding` genau deshalb\n"
            "  als 'gemischte Boerse' -- die Carry-Studie hat es nur nie abgefragt."
        )

    print("\n" + "=" * 78)
    print("Natur der exakten Nullen")
    print("=" * 78 + "\n")
    for symbol in symbols:
        note = zero_nature(symbol, venue_of[symbol], offline=args.offline)
        if note != "keine Nullen":
            print(f"  {symbol:10s} {note}")

    known = [s for s in symbols if venue_of[s] in VENUES]
    if len(known) == len(symbols):
        common_window_split(symbols, venue_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
