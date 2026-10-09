"""Die Payload-Felder der USDⓈ-M-Futures-Streams an der echten Verbindung prüfen.

    python scripts/probe_futures_streams.py

**Warum als eigenes Skript.** Der Forschungsauftrag verlangt, die aktuellen
Endpunkte und Payloads *vor* der Implementierung anhand der offiziellen
Dokumentation zu prüfen, und ausdrücklich keine Spot-Beispiele ungeprüft zu
übernehmen. Die Dokumentationsseite zu den Feldern liess sich nicht abrufen --
also wird hier gegen die Quelle selbst geprüft statt gegen mein Gedächtnis.

Was aus der Dokumentation **belegt** vorliegt (Seite *How to manage a local
order book correctly*, USDⓈ-M-Futures-Fassung):

    3. Snapshot: https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000
    4. "Drop any event where `u` is < `lastUpdateId` in the snapshot."
    5. "The first processed event should have `U` <= `lastUpdateId`
        AND `u` >= `lastUpdateId`"
    6. "each new event's `pu` should be equal to the previous event's `u`,
        otherwise initialize the process from step 3."
    7./8. Mengen sind absolut je Preisniveau; Menge 0 heisst Niveau entfernen.
    9. Ein Entfernen eines Niveaus, das lokal nicht existiert, ist normal.

`pu` ist der Unterschied zur Spot-Fassung. Spot kennt es nicht und prüft
`U == voriges u + 1`. Wer das Spot-Verfahren auf Futures anwendet,
invalidiert sein Buch bei jedem zweiten Ereignis oder, schlimmer, nie.

**Nur lesen.** Öffentliche Streams, kein Schlüssel, keine Order.
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: Belegter Basis-Endpunkt aus der Futures-Dokumentation.
WS_BASE = "wss://fstream.binance.com"

#: Belegter REST-Snapshot aus Schritt 3 derselben Seite.
SNAPSHOT = "https://fapi.binance.com/fapi/v1/depth"

#: Die drei Streams, die Phase 3 des Auftrags nennt. Tiefe mit 100 ms, weil
#: die Dokumentation 100 ms und 500 ms als Optionen nennt und der kürzere
#: Takt die Sequenzprüfung härter testet.
STREAMS = ("btcusdt@depth@100ms", "btcusdt@aggTrade", "btcusdt@bookTicker")

#: So viele Nachrichten je Stream genügen, um die Felder zu sehen.
WANTED = 2

TIMEOUT = 25.0


def snapshot_keys(symbol: str) -> dict[str, object]:
    """Felder des REST-Snapshots, und seine `lastUpdateId`."""
    url = f"{SNAPSHOT}?symbol={symbol}&limit=1000"
    with urllib.request.urlopen(url, timeout=15) as answer:
        body = json.loads(answer.read())
    return {
        "keys": sorted(body.keys()),
        "lastUpdateId": body.get("lastUpdateId"),
        "bids": len(body.get("bids") or []),
        "asks": len(body.get("asks") or []),
        "E": body.get("E"),
        "T": body.get("T"),
    }


async def probe() -> int:
    url = f"{WS_BASE}/stream?streams={'/'.join(STREAMS)}"
    print("=" * 84)
    print("Payload-Pruefung der USDS-M-Futures-Streams, an der echten Verbindung")
    print("=" * 84)
    print(f"\n  {url}\n")

    seen: dict[str, list[dict]] = {name: [] for name in STREAMS}
    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as socket:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TIMEOUT
        while any(len(v) < WANTED for v in seen.values()) and loop.time() < deadline:
            raw = await asyncio.wait_for(socket.recv(), timeout=deadline - loop.time())
            message = json.loads(raw)
            name = message.get("stream", "?")
            payload = message.get("data", message)
            if name in seen and len(seen[name]) < WANTED:
                seen[name].append(payload)

    for name, messages in seen.items():
        print("-" * 84)
        print(f"  {name}   {len(messages)} Nachricht(en)")
        if not messages:
            print("    nichts empfangen")
            continue
        first = messages[0]
        print(f"    Felder: {sorted(first.keys())}")
        for key, value in sorted(first.items()):
            shown = value if not isinstance(value, list) else f"<{len(value)} Einträge> {value[:1]}"
            print(f"      {key:4s} = {str(shown)[:70]}")
        if len(messages) >= 2 and "u" in first and "pu" in messages[1]:  # noqa: PLR2004
            ok = messages[1]["pu"] == first["u"]
            print(f"    Kontinuitaet pu == voriges u: {ok}  "
                  f"({messages[1]['pu']} gegen {first['u']})")

    print("-" * 84)
    print("  REST-Snapshot (Schritt 3 der Dokumentation):")
    for key, value in snapshot_keys("BTCUSDT").items():
        print(f"    {key:14s} {value}")
    print("\n  Nur gelesen. Kein Schluessel, keine Order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(probe()))
