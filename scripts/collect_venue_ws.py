"""Den Websocket-Strom von Lighter aufzeichnen -- roh, mit Empfangszeit.

**Warum es diesen zweiten Sammler gibt.** `collect_venue_tape.py` FRAGT das
Buch ab. Gemessen am 20.10. erreicht er bestenfalls 2.35 s je Markt; schneller
antwortet die Boerse nicht mehr, sondern drosselt (mit `--book-every 1` lief er
genau 70 Sekunden und sammelte danach 8.190 Fehler "HTTP 405" am Stueck).

Damit ist die Frage, auf die es ankommt, grundsaetzlich unbeantwortbar: 93.2 %
der beobachteten Touch-Leben dauerten genau EINEN Rasterschritt. Die wahre
Standzeit liegt unter dem Raster. Der berichtete "Median 2.36 s" war die
mittlere Kadenz (2.356 s) auf drei Stellen genau -- die Messung beschrieb den
Apparat, nicht den Markt.

Der Websocket SCHIEBT. Gemessen: rund 18 Nachrichten je Sekunde und Markt,
also ~55 ms zwischen zwei Buchaenderungen -- 43-mal feiner als die Abfrage, auf
EINER Verbindung, die die Boerse weniger kostet als das Abfragen.

**Was er zusaetzlich traegt, und was er nicht traegt.** Das Trade-Band im
Strom hat mehr Felder als das der REST-Schnittstelle, darunter
`maker_position_size_before`: der Lagerbestand des Makers VOR dem Geschaeft.
Damit laesst sich erstmals sehen, ob die Maker hier Bestand halten oder sofort
glattstellen. Dafuer gibt es KEINEN Kanal mit einzelnen Order-IDs im Buch
(`order_book_orders` antwortet "Invalid Channel") -- die Ebenen sind
aggregiert. Order-Identitaet bleibt der REST-Aufnahme vorbehalten. Die beiden
Sammler ersetzen einander nicht.

**Roh schreiben, nicht deuten.** Die erste Nachricht je Kanal ist ein voller
Abzug (703 bis 2.767 Ebenen), alle weiteren sind Aenderungen (im Mittel 8-12
Ebenen, `size: "0.00000"` heisst geloescht). Das Zusammensetzen passiert bei
der Auswertung, nicht hier. Ein Sammler, der schon deutet, kann einen Fehler im
Deuten nicht mehr sichtbar machen.

**Luecken sind ein Ereignis, kein Nichts.** Jede Nachricht traegt ein `offset`.
Springt es, sind Nachrichten verloren, und das wird als eigene Zeile
`{"typ": "luecke"}` festgehalten -- genauso jeder Verbindungsabbruch. Eine
Stichprobe mit unsichtbaren Loechern ist schlimmer als eine mit sichtbaren,
weil man ihr die Loecher nicht ansieht.

    python scripts/collect_venue_ws.py --hours 11 --markets BTC,ETH,SOL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

import websockets

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "quarantine" / "venue_ws"
URL = "wss://mainnet.zklighter.elliot.ai/stream"

#: market_id der Boerse. Nachgesehen in /api/v1/orderBooks, nicht geraten:
#: ETH ist 0, BTC ist 1, SOL ist 2 -- die Reihenfolge ist NICHT alphabetisch
#: und nicht nach Groesse.
MARKT_ID = {"ETH": 0, "BTC": 1, "SOL": 2}

#: Eimergroesse der Ausgabedateien. Eine Stunde, wie bei der REST-Aufnahme,
#: damit beide Sammler dieselben Zeitgrenzen haben und sich vergleichen lassen.
EIMER_MS = 3_600_000

#: Fortschrittszeile. 600 s, nicht kuerzer: eine Logdatei, die im Sekundentakt
#: waechst, verdeckt die Zeilen, auf die es ankommt (Luecken, Abbrueche).
NOTIZ_ALLE = 600.0

#: Nach einem Abbruch warten, bevor neu verbunden wird. Waechst bis zum
#: Deckel, damit ein laengerer Ausfall nicht zum Dauerfeuer wird.
WARTE_START = 2.0
WARTE_DECKEL = 60.0


class Schreiber:
    """Eine offene Datei je Markt und Stunde. Jede Zeile wird gespuelt.

    `flush` steht hier am Schreiben und nicht am Oeffnen. Am 12.10. war die
    Schlussmeldung des Papierhaendlers sein ganzes Leben lang unsichtbar, weil
    der Puffer nie geleert wurde. Eine Zeile, die nicht ankommt, ist kein
    Protokoll.
    """

    def __init__(self, wurzel: pathlib.Path) -> None:
        self.wurzel = wurzel
        self._offen: dict[tuple[str, int], object] = {}

    def schreibe(self, symbol: str, satz: dict) -> int:
        eimer = int(satz["empfangen_ms"]) // EIMER_MS * EIMER_MS
        schluessel = (symbol, eimer)
        fh = self._offen.get(schluessel)
        if fh is None:
            for (s, _), alt in list(self._offen.items()):
                if s == symbol:
                    alt.close()
                    del self._offen[(s, _)]
            ordner = self.wurzel / symbol
            ordner.mkdir(parents=True, exist_ok=True)
            fh = (ordner / f"strom-{eimer}.jsonl").open("a", encoding="utf-8")
            self._offen[schluessel] = fh
        zeile = json.dumps(satz, separators=(",", ":"))
        fh.write(zeile + "\n")
        fh.flush()
        return len(zeile) + 1

    def schliesse(self) -> None:
        for fh in self._offen.values():
            fh.close()
        self._offen.clear()


def sag(zeile: str) -> None:
    print(zeile, flush=True)


async def lauf(maerkte: list[str], deadline: float, schreiber: Schreiber) -> dict:
    """Eine Verbindung, bis sie abreisst oder die Zeit um ist."""
    id_zu_symbol = {MARKT_ID[m]: m for m in maerkte}
    zaehler = {"nachrichten": 0, "trades": 0, "buecher": 0, "bytes": 0, "luecken": 0}
    letztes_offset: dict[str, int] = {}

    async with websockets.connect(
        URL, open_timeout=20, close_timeout=5, max_size=16 * 2**20,
        ping_interval=20, ping_timeout=20,
    ) as ws:
        await asyncio.wait_for(ws.recv(), timeout=15)  # {"type":"connected"}
        for m in maerkte:
            mid = MARKT_ID[m]
            await ws.send(json.dumps({"type": "subscribe", "channel": f"order_book/{mid}"}))
            await ws.send(json.dumps({"type": "subscribe", "channel": f"trade/{mid}"}))

        while time.time() < deadline:
            roh = await asyncio.wait_for(ws.recv(), timeout=90)
            empfangen_ms = int(time.time() * 1000)
            nachricht = json.loads(roh)
            kanal = nachricht.get("channel")
            if not kanal or ":" not in kanal:
                continue
            art, _, mid_text = kanal.partition(":")
            symbol = id_zu_symbol.get(int(mid_text)) if mid_text.isdigit() else None
            if symbol is None:
                continue

            # -- Luecke pruefen, BEVOR der Satz geschrieben wird ------------ #
            offset = nachricht.get("offset")
            if isinstance(offset, int):
                schluessel = f"{symbol}:{art}"
                vorher = letztes_offset.get(schluessel)
                if vorher is not None and offset < vorher:
                    zaehler["luecken"] += 1
                    schreiber.schreibe(symbol, {
                        "typ": "luecke", "empfangen_ms": empfangen_ms,
                        "kanal": art, "offset_vorher": vorher, "offset_jetzt": offset,
                    })
                letztes_offset[schluessel] = offset

            zaehler["bytes"] += schreiber.schreibe(symbol, {
                "typ": art, "empfangen_ms": empfangen_ms, "nachricht": nachricht,
            })
            zaehler["nachrichten"] += 1
            if art == "trade":
                zaehler["trades"] += len(nachricht.get("trades") or [])
            else:
                zaehler["buecher"] += 1

    return zaehler


async def hauptschleife(maerkte: list[str], stunden: float) -> int:
    schreiber = Schreiber(OUT)
    begonnen = time.time()
    deadline = begonnen + stunden * 3600
    gesamt = {"nachrichten": 0, "trades": 0, "buecher": 0, "bytes": 0, "luecken": 0, "abbrueche": 0}
    warte = WARTE_START
    letzte_notiz = begonnen

    try:
        while time.time() < deadline:
            try:
                z = await lauf(maerkte, deadline, schreiber)
                for k, v in z.items():
                    gesamt[k] += v
                warte = WARTE_START
            except asyncio.CancelledError:
                raise
            except Exception as problem:  # noqa: BLE001
                gesamt["abbrueche"] += 1
                jetzt_ms = int(time.time() * 1000)
                for m in maerkte:
                    schreiber.schreibe(m, {
                        "typ": "abbruch", "empfangen_ms": jetzt_ms,
                        "grund": f"{type(problem).__name__}: {str(problem)[:200]}",
                    })
                sag(f"  ! ABBRUCH ({gesamt['abbrueche']}x): "
                    f"{type(problem).__name__}: {str(problem)[:120]}")
                sag(f"    neuer Versuch in {warte:.0f}s")
                if time.time() + warte >= deadline:
                    break
                await asyncio.sleep(warte)
                warte = min(WARTE_DECKEL, warte * 2)

            if time.time() - letzte_notiz >= NOTIZ_ALLE:
                gelaufen = (time.time() - begonnen) / 3600
                sag(f"  [{gelaufen:5.2f}h] {gesamt['nachrichten']:,} Nachrichten, "
                    f"{gesamt['buecher']:,} Buchaenderungen, {gesamt['trades']:,} Trades, "
                    f"{gesamt['bytes'] / 2**20:,.0f} MB, {gesamt['luecken']} Luecken, "
                    f"{gesamt['abbrueche']} Abbrueche")
                letzte_notiz = time.time()
    except KeyboardInterrupt:
        sag("\n  Abgebrochen. Was geschrieben ist, bleibt.")
    finally:
        schreiber.schliesse()

    dauer = (time.time() - begonnen) / 3600
    sag("\n" + "=" * 72)
    sag(f"  {dauer:.2f} h  |  {gesamt['nachrichten']:,} Nachrichten  "
        f"|  {gesamt['buecher']:,} Buchaenderungen  |  {gesamt['trades']:,} Trades")
    sag(f"  {gesamt['bytes'] / 2**20:,.0f} MB geschrieben nach {OUT}")
    sag(f"  {gesamt['luecken']} Luecken, {gesamt['abbrueche']} Abbrueche "
        f"-- beide stehen als eigene Zeilen in den Daten.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hours", type=float, default=11.0)
    p.add_argument("--markets", default="BTC,ETH,SOL")
    a = p.parse_args(argv)

    maerkte = [s.strip().upper() for s in a.markets.split(",") if s.strip()]
    unbekannt = [m for m in maerkte if m not in MARKT_ID]
    if unbekannt:
        raise SystemExit(f"Unbekannte Maerkte: {unbekannt}. Bekannt: {sorted(MARKT_ID)}")

    sag("=" * 72)
    sag("Websocket-Aufnahme: Buchaenderungen UND Trades, mit Empfangszeit")
    sag("=" * 72)
    sag(f"\n  Dauer    {a.hours} h")
    sag(f"  Maerkte  {', '.join(f'{m} (id {MARKT_ID[m]})' for m in maerkte)}")
    sag(f"  Ziel     {OUT}")
    sag("  Kadenz   gemessen ~55 ms je Markt -- 43x feiner als die Abfrage")
    sag("  Luecken und Abbrueche stehen als eigene Zeilen in den Daten.")
    sag("\n  Nur lesen. Kein Schluessel, keine Order.\n")

    return asyncio.run(hauptschleife(maerkte, a.hours))


if __name__ == "__main__":
    sys.exit(main())
