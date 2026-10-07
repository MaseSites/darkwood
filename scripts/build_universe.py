"""Das Point-in-Time-Universum bauen -- der Blocker von E4.

    python scripts/build_universe.py
    python scripts/build_universe.py --refresh-dates

**Was blockiert war.** E4 (marktbereinigte Relative-Value-Entscheidung)
stand im Register mit einem benannten Hindernis: Survivorship. Jede
marktübergreifende Zahl, die aus den heute handelbaren Symbolen gerechnet
wird, hat die Verlierer schon weggelassen -- und zwar genau die, deren
Verschwinden die Rendite gekostet hätte. Das Datenmanifest führt
`point_in_time_universe` als Priorität 1.

**Was es aufhebt.** Zwei öffentliche, rein lesende Quellen, beide am
07.10.2026 geprüft:

* `fapi/v1/exchangeInfo` liefert je Symbol ein **`onboardDate`** -- das
  Listing-Datum. Damit ist die eine Hälfte da.
* Das öffentliche Archiv (`data.binance.vision`) listet
  **Verzeichnisse für Symbole, die `exchangeInfo` nicht mehr kennt.**
  1'061 Symbole im Archiv gegen 924 live. Das ist die andere Hälfte: die
  Delisteten.

Damit ist "welche Symbole waren an Tag X handelbar" beantwortbar statt
geschätzt.

**Drei Fallen, die das Rohmaterial stellt.**

*Die Quote-Währung.* 70 Symbole im Archiv enden auf `BUSD`. BUSD ist
eingestellt; das sind keine USDT-Perps und gehören nicht in ein
USDT-Universum. Sie werden getrennt ausgewiesen, nicht stillschweigend
mitgezählt.

*Die `SETTLED`-Suffixe.* 17 Symbole tragen `SETTLED` im Namen, eines davon
sogar `SETTLEDSETTLED`. Das sind Abwicklungsstände desselben Instruments,
keine eigenen Märkte. Wer sie als Symbole zählt, zählt denselben Markt
mehrfach.

*Das Delisting-Datum ist nicht gegeben, nur eingegrenzt.* Das Archiv sagt,
welcher Tag der letzte mit Daten war. Das ist eine **Untergrenze** für das
Delisting und wird als solche gespeichert -- nicht als Datum. Ein Modell,
das auf den Tag genau aussteigen muss, braucht mehr; eines, das wissen
muss, ob ein Symbol in einem Monat noch existierte, kommt damit aus.

**Was das hier nicht ist.** Kein E4. Dieses Skript baut die Tabelle, die
E4 gebraucht hätte, und nimmt dem Register damit einen Blocker -- es
rechnet kein Experiment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
ARCHIVE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
KLINES_PREFIX = "data/futures/um/daily/klines/"

OUT = ROOT / "data" / "universe"
TIMEOUT = 30.0

#: S3 antwortet hier in ListObjects **v1** (ohne `list-type=2`), und v1
#: blaettert mit `marker=`, nicht mit `continuation-token`. Eine erste
#: Fassung benutzte v2-Semantik, bekam genau 1'000 Symbole -- das
#: Standardlimit -- und haielt das fuer die ganze Liste. 1'000 ist die Zahl,
#: bei der man nachsehen muss, ob noch etwas kommt.
PAGE_GUARD = 20

#: Wie viele delistete Symbole der Bericht namentlich nennt, bevor er zaehlt.
SHOW = 8

#: Datierte Lieferfutures: `BTCUSDT_210326`. Die sind NICHT delistet, sie
#: sind ABGELAUFEN -- das ist ihre Konstruktion.
#:
#: Die erste Fassung zaehlte sie mit und meldete 8.1% Survivorship. 46 der
#: 77 "Delistings" waren Quartalsfutures; die echten Perp-Delistings sind
#: 31 von 910, also 3.4%. Ein Faktor 2.4 daneben -- gefangen daran, dass
#: `BTCUSDT_210326` im Bericht auffiel. Eine Zahl, die aus einer
#: Namensliste kommt, muss die Namen ansehen.
DATED_FUTURE = re.compile(r"_\d{6}$")


@dataclass(frozen=True, slots=True)
class Entry:
    symbol: str
    quote: str
    #: Listing-Datum aus exchangeInfo, in ms. 0 wenn das Symbol dort nicht
    #: mehr steht -- dann ist es delistet und das Datum ist verloren.
    onboard_ms: int
    status: str
    in_archive: bool
    #: Letzter Tag mit Archivdaten, als ISO-Datum. UNTERGRENZE fuer das
    #: Delisting, kein Delisting-Datum.
    last_data: str = ""
    #: Abwicklungsstand statt eigener Markt (`SETTLED` im Namen).
    settled_marker: bool = False


def read(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
        return answer.read()


def live_symbols() -> dict[str, tuple[int, str, str]]:
    """Symbol -> (onboardDate, status, quoteAsset), wie die Boerse es sagt."""
    payload = json.loads(read(EXCHANGE_INFO))
    return {
        s["symbol"]: (
            int(s.get("onboardDate") or 0),
            str(s.get("status") or ""),
            str(s.get("quoteAsset") or ""),
        )
        for s in payload["symbols"]
    }


def archive_symbols() -> list[str]:
    """Alle Symbolverzeichnisse im Archiv, ueber alle Seiten."""
    base = f"{ARCHIVE}?delimiter=/&prefix={KLINES_PREFIX}"
    found: list[str] = []
    marker: str | None = None
    for _ in range(PAGE_GUARD):
        url = base + (f"&marker={urllib.parse.quote(marker)}" if marker else "")
        xml = read(url).decode()
        page = re.findall(rf"<Prefix>{re.escape(KLINES_PREFIX)}([^/]+)/</Prefix>", xml)
        found.extend(page)
        if "<IsTruncated>true</IsTruncated>" not in xml or not page:
            return sorted(set(found))
        marker = KLINES_PREFIX + page[-1] + "/"
    raise RuntimeError(f"Archivliste nach {PAGE_GUARD} Seiten nicht zu Ende -- unerwartet.")


def last_archive_day(symbol: str) -> str:
    """Letzter Tag mit 1d-Daten im Archiv. Leer, wenn nichts da ist."""
    prefix = f"{KLINES_PREFIX}{symbol}/1d/"
    url = f"{ARCHIVE}?prefix={urllib.parse.quote(prefix)}"
    try:
        xml = read(url).decode()
    except (urllib.error.URLError, TimeoutError, OSError):
        return ""
    days = re.findall(rf"{re.escape(symbol)}-1d-(\d{{4}}-\d{{2}}-\d{{2}})\.zip", xml)
    return max(days) if days else ""


def build(*, fetch_dates: bool) -> list[Entry]:
    live = live_symbols()
    archive = set(archive_symbols())
    print(f"  exchangeInfo: {len(live):,} Symbole   Archiv: {len(archive):,} Symbole")

    names = sorted(set(live) | archive)
    out: list[Entry] = []
    delisted = [n for n in names if n not in live and n in archive]
    print(f"  Im Archiv, nicht mehr live: {len(delisted):,}")

    dates: dict[str, str] = {}
    if fetch_dates and delisted:
        print(f"  Letzten Archivtag holen fuer {len(delisted):,} delistete Symbole ...")
        for i, name in enumerate(delisted, 1):
            dates[name] = last_archive_day(name)
            if i % 25 == 0:
                print(f"    {i:4d}/{len(delisted)}", flush=True)

    for name in names:
        onboard, status, quote = live.get(name, (0, "", ""))
        if not quote:
            # Nicht mehr live: die Quote-Waehrung aus dem Namen erschliessen.
            # Das ist eine Heuristik und wird so benannt.
            for candidate in ("USDT", "BUSD", "USDC"):
                if name.endswith(candidate) or candidate in name:
                    quote = candidate
                    break
            else:
                quote = "?"
        out.append(
            Entry(
                symbol=name,
                quote=quote,
                onboard_ms=onboard,
                status=status or "DELISTED",
                in_archive=name in archive,
                last_data=dates.get(name, ""),
                settled_marker="SETTLED" in name,
            )
        )
    return out


def report(entries: list[Entry]) -> None:
    usdt = [
        e
        for e in entries
        if e.quote == "USDT" and not e.settled_marker and not DATED_FUTURE.search(e.symbol)
    ]
    dated = [e for e in entries if DATED_FUTURE.search(e.symbol)]
    print("\n" + "=" * 78)
    print("  Das Universum, nach Gruppen")
    print("=" * 78)
    states: dict[str, int] = {}
    for e in entries:
        states[e.status] = states.get(e.status, 0) + 1
    print(f"\n  Alle Eintraege: {len(entries):,}")
    for state, count in sorted(states.items(), key=lambda kv: -kv[1]):
        print(f"    {state:18s} {count:>5,}")

    print(
        f"\n  Datierte Lieferfutures (_YYMMDD): {len(dated):,} -- AUSGESCHLOSSEN.\n"
        f"    Sie sind nicht delistet, sondern abgelaufen; das ist ihre Konstruktion.\n"
        f"    Sie mitzuzaehlen hat in der ersten Fassung 8.1% Survivorship gemeldet."
    )
    print(f"\n  USDT-PERPS, ohne SETTLED und ohne datierte Futures: {len(usdt):,}")
    live_usdt = [e for e in usdt if e.status != "DELISTED"]
    gone = [e for e in usdt if e.status == "DELISTED"]
    print(f"    heute handelbar oder abwickelnd: {len(live_usdt):,}")
    print(f"    DELISTET:                        {len(gone):,}")

    if gone:
        share = 100 * len(gone) / len(usdt)
        print(
            f"\n  Das ist der Survivorship-Bias in einer Zahl: **{share:.1f}%** der\n"
            f"  USDT-PERPS, die es je gab, sind heute weg. Jede marktuebergreifende\n"
            f"  Rechnung aus der HEUTIGEN Liste laesst sie aus -- und zwar genau die,\n"
            f"  deren Verschwinden Geld gekostet haette."
        )
        with_date = [e for e in gone if e.last_data]
        print(f"\n  Mit letztem Archivtag belegt: {len(with_date):,} von {len(gone):,}")
        for e in sorted(with_date, key=lambda x: x.last_data)[:SHOW]:
            print(f"    {e.symbol:22s} letzte Daten {e.last_data}")
        if len(with_date) > SHOW:
            print(f"    ... und {len(with_date) - SHOW:,} weitere")

    print(
        "\n  ACHTUNG, und das gehoert neben jede Zahl oben: `last_data` ist der\n"
        "  letzte Tag MIT DATEN, also eine UNTERGRENZE fuer das Delisting, kein\n"
        "  Delisting-Datum. Und das `onboardDate` fehlt fuer jedes delistete\n"
        "  Symbol -- exchangeInfo kennt es nicht mehr, also ist sein Listing-Datum\n"
        "  aus dieser Quelle verloren. Der erste Archivtag waere der Ersatz."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-dates",
        action="store_true",
        help="Letzten Archivtag je delistetem Symbol holen (eine Anfrage je Symbol).",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("Point-in-Time-Universum -- der Blocker von E4")
    print("=" * 78 + "\n")

    entries = build(fetch_dates=args.refresh_dates)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "binance_um_perps.json"
    payload = {
        "source": {
            "live": EXCHANGE_INFO,
            "archive": f"{ARCHIVE}?prefix={KLINES_PREFIX}",
        },
        "caveats": [
            "last_data ist der letzte Tag MIT DATEN, eine Untergrenze fuer das Delisting.",
            "onboard_ms fehlt fuer delistete Symbole -- exchangeInfo kennt sie nicht mehr.",
            "quote ist fuer delistete Symbole aus dem NAMEN erschlossen, eine Heuristik.",
            "SETTLED-Eintraege sind Abwicklungsstaende desselben Instruments, keine Maerkte.",
            "BUSD ist eine andere Quote-Waehrung und gehoert nicht in ein USDT-Universum.",
        ],
        "entries": [
            {
                "symbol": e.symbol,
                "quote": e.quote,
                "onboard_ms": e.onboard_ms,
                "status": e.status,
                "in_archive": e.in_archive,
                "last_data": e.last_data,
                "settled_marker": e.settled_marker,
            }
            for e in entries
        ],
    }
    target.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    report(entries)
    print(f"\n  Gespeichert: {target}")
    print(
        "\n  Damit ist E4s benannter Blocker ('Point-in-time-Universum und\n"
        "  Delisting-Abrechnung') aufgehoben. E4 selbst ist damit nicht gerechnet."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
