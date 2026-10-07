"""Nicht-Fills, Cancels und Markouts — aus den Büchern, die schon da liegen.

Der Forschungsauftrag verlangt für E0 ausdrücklich mehr als die Gebühr:
„Erfasse Nicht-Fills, Teil-Fills, verfallene Signale, Cancel-Verzögerung und
tatsächliche verfügbare Orderbuchgrösse." Der erste E0-Schritt hat nur die
Kosten beantwortet, und der Bericht hat den Rest als offen vermerkt.

**Warum das ohne eine einzige Order messbar ist.** Das Buch dieser Venue ist
nicht aggregiert. Jede Zeile ist eine *einzelne Order* mit `order_id`,
`order_index`, `initial_base_amount` und `remaining_base_amount`. Damit lässt
sich dieselbe Order über mehrere Aufnahmen hinweg verfolgen — und das ist
genau die Beobachtung, für die man sonst selbst handeln müsste:

* Wird `remaining_base_amount` kleiner, ist diese Order **teilweise gefüllt
  worden**. Das ist der einzige *direkte* Beleg für einen Fill in diesen
  Daten, und er braucht keine Annahme.
* Verschwindet eine Order, während der Preis nicht durch sie hindurchgelaufen
  ist, wurde sie **storniert**. Eine Order, die man nicht bekommt, weil der
  Gegenpart sie wegzieht, ist der Nicht-Fill, den ein Backtest nie sieht.
* `order_index` ordnet innerhalb eines Preisniveaus, also ist die
  **Warteschlange vor einem Einstieg** zählbar statt geschätzt.

**Was hier bewusst NICHT behauptet wird.** Ohne Trade-Tape ist „gefüllt" bei
einer *vollständig* verschwundenen Order eine Folgerung, nicht eine
Beobachtung: ein Massen-Cancel über mehrere Niveaus sieht aus wie ein Sweep.
Darum werden drei Klassen getrennt berichtet und nicht zu einer Fill-Rate
verrechnet. Der Teil-Fill ist der harte Beleg; der Rest ist benannt, wie er
zustande kommt.

**Die Aufnahme ist klein und das ist eine Grenze, keine Fussnote.** Fünf
Aufnahmen je Markt, ~17 s auseinander, an einem Vormittag, ohne Stressphase.
Das reicht, um die Messung zu belegen und eine erste Lesung zu geben. Es
charakterisiert diese Venue nicht. Die Horizonte 1 s und 5 s, die der Auftrag
nennt, brauchen einen Streaming-Collector; 5 min braucht eine längere
Aufnahme. Beides steht als nächster Schritt, nicht als Ergebnis.

Die Uhr ist die **lokale Empfangszeit** der Datei, nicht die Buchzeit der
Börse — `transaction_time` steht in diesen Antworten auf 0. Der Auftrag
verlangt lokale Empfangszeiten, also ist das die richtige Uhr; sie ist nur
nicht dieselbe wie die der Börse.

    ./.venv/Scripts/python.exe scripts/study_venue_fills.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CACHE = ROOT / "data" / "quarantine" / "venue_cost"

#: Die Grösse, auf die sich jede Aussage über die Warteschlange bezieht. Das
#: ist der Betrag, mit dem dieses Projekt handeln würde, nicht eine runde Zahl.
NOTIONAL_USD = 1_000.0

#: Unter zwei Aufnahmen gibt es keinen Uebergang zu beobachten.
MIN_SNAPSHOTS = 2

#: Unter so wenigen belegten Fills wird der Markout als Ereignisliste
#: berichtet und nicht als Schaetzung. Die Grenze ist vor dem Lauf
#: gesetzt, nicht nach dem Blick auf die Zahlen.
MIN_FILLS = 30


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    index: int
    price: float
    remaining: float
    initial: float


@dataclass(frozen=True, slots=True)
class Book:
    asks: list[Order]
    bids: list[Order]
    received_ms: int

    @property
    def best_ask(self) -> float:
        return self.asks[0].price

    @property
    def best_bid(self) -> float:
        return self.bids[0].price

    @property
    def mid(self) -> float:
        return 0.5 * (self.best_ask + self.best_bid)


@dataclass(frozen=True, slots=True)
class Transition:
    """Was zwischen zwei Aufnahmen mit den Orders der ersten passiert ist."""

    seconds: float
    tracked: int
    #: Harter Beleg: dieselbe Order, weniger übrig.
    partial: int
    partial_volume: float
    #: Verschwunden, und der Preis ist durch sie hindurchgelaufen.
    swept: int
    #: Verschwunden, obwohl der Preis sie nie erreicht hat -- ein Cancel.
    cancelled: int
    unchanged: int
    mid_before: float
    mid_after: float

    @property
    def cancel_share(self) -> float:
        return self.cancelled / max(1, self.tracked)

    @property
    def markout_bp(self) -> float:
        """Mid-Bewegung in Basispunkten, Vorzeichen wie der Markt."""
        return 10_000.0 * (self.mid_after - self.mid_before) / self.mid_before


def read_book(path: Path) -> Book:
    payload = json.loads(path.read_text(encoding="utf-8"))

    def side(rows: list[dict]) -> list[Order]:
        return [
            Order(
                order_id=str(row["order_id"]),
                index=int(row["order_index"]),
                price=float(row["price"]),
                remaining=float(row["remaining_base_amount"]),
                initial=float(row["initial_base_amount"]),
            )
            for row in rows
        ]

    asks = sorted(side(payload["asks"]), key=lambda o: o.price)
    bids = sorted(side(payload["bids"]), key=lambda o: -o.price)
    # Empfangszeit aus der Datei, weil die Antwort selbst keine traegt.
    received_ms = int(path.stat().st_mtime * 1000)
    return Book(asks=asks, bids=bids, received_ms=received_ms)


def queue_ahead(book: Book, *, side: str) -> tuple[float, float]:
    """Wie viel am Antrittspreis vor einem neuen Eintritt liegt.

    Rückgabe: (Volumen am Antritt in USD, Anteil, den `NOTIONAL_USD` davon
    ausmacht). Eine Order ganz hinten in dieser Schlange füllt erst, wenn
    alles davor gefüllt ist -- das ist der Grund, warum eine Maker-Absicht
    keine Maker-Ausführung ist.
    """
    orders = book.asks if side == "ask" else book.bids
    touch = orders[0].price
    at_touch = [o for o in orders if o.price == touch]
    volume_usd = sum(o.remaining * o.price for o in at_touch)
    return volume_usd, NOTIONAL_USD / volume_usd if volume_usd > 0 else float("inf")


def transition(before: Book, after: Book, *, side: str) -> Transition:
    """Die Orders der ersten Aufnahme, nachverfolgt in der zweiten."""
    old = before.asks if side == "ask" else before.bids
    new = after.asks if side == "ask" else after.bids
    seen = {o.order_id: o for o in new}

    # Wie weit der Preis gelaufen ist. Fuer Asks heisst "durchgelaufen",
    # dass der beste Ask GESTIEGEN ist: alles darunter ist weg.
    if side == "ask":
        frontier = after.best_ask

        def swept_through(price: float) -> bool:
            return price < frontier
    else:
        frontier = after.best_bid

        def swept_through(price: float) -> bool:
            return price > frontier

    partial = 0
    partial_volume = 0.0
    swept = 0
    cancelled = 0
    unchanged = 0

    for order in old:
        match = seen.get(order.order_id)
        if match is None:
            if swept_through(order.price):
                swept += 1
            else:
                cancelled += 1
            continue
        if match.remaining < order.remaining - 1e-12:
            partial += 1
            partial_volume += (order.remaining - match.remaining) * order.price
        else:
            unchanged += 1

    return Transition(
        seconds=(after.received_ms - before.received_ms) / 1000.0,
        tracked=len(old),
        partial=partial,
        partial_volume=partial_volume,
        swept=swept,
        cancelled=cancelled,
        unchanged=unchanged,
        mid_before=before.mid,
        mid_after=after.mid,
    )


def mid_drift(books: list[Book]) -> list[tuple[float, float]]:
    """Unbedingte Mid-Bewegung je Horizont, in Basispunkten.

    **Das ist ausdrücklich KEIN Markout**, und die erste Fassung dieses
    Skripts hat es so genannt. Ein Markout misst, wie sich der Preis
    bewegt, *nachdem man gefüllt wurde* — er bedingt auf den Fill, und
    genau daraus entsteht die Aussage über adverse Selektion. Diese Zahl
    bedingt auf nichts. Sie sagt, wie weit der Markt in dem Fenster
    gelaufen ist.

    Sie steht trotzdem hier, weil der bedingte Markout ohne sie nicht zu
    lesen ist: wenn der Markt in diesen zwei Minuten um +5 bp gestiegen
    ist, dann ist ein Verkäufer-Markout von +5 bp kein Befund über die
    Fill-Qualität, sondern derselbe Marktlauf noch einmal.
    """
    out: list[tuple[float, float]] = []
    for lag in range(1, len(books)):
        moves = [
            10_000.0 * (books[i + lag].mid - books[i].mid) / books[i].mid
            for i in range(len(books) - lag)
        ]
        seconds = float(
            np.mean(
                [
                    (books[i + lag].received_ms - books[i].received_ms) / 1000.0
                    for i in range(len(books) - lag)
                ]
            )
        )
        out.append((seconds, float(np.mean(moves))))
    return out


@dataclass(frozen=True, slots=True)
class Reduction:
    """Eine Order, deren `remaining` kleiner geworden ist.

    **Nicht „ein Fill".** Die erste Fassung dieses Skripts nannte das den
    harten Beleg für eine Ausführung, und ein einziger Fall hat das
    widerlegt: auf LINK schrumpfte eine Order **394 bp** vom Mid entfernt.
    Ein Ask 4 % über dem Markt wird in 17 Sekunden nicht gehandelt. Der
    Eigentümer hat die Grösse reduziert.

    Ohne Trade-Tape lässt sich eine Teilausführung von einer Teil-Storno
    also nicht unterscheiden. Was sich unterscheiden lässt, ist, ob der
    Preis überhaupt **erreichbar** war -- und das schliesst den LINK-Fall
    aus, ohne eine Schwelle zu erfinden.
    """

    side: str
    price: float
    volume_usd: float
    #: Index der Aufnahme, in der die Verkleinerung sichtbar wurde.
    at: int
    #: War dieser Preis im Fenster überhaupt vom Markt erreicht?
    reachable: bool


def size_reductions(books: list[Book]) -> list[Reduction]:
    """Jede Order, deren verbleibende Menge geschrumpft ist.

    Die Erreichbarkeit ist eine **notwendige** Bedingung aus den Daten, kein
    gewählter Abstand: ein Ask bei `P` kann nur gehandelt worden sein, wenn
    der beste Ask im Fenster irgendwann mindestens `P` erreicht hat -- sonst
    war `P` nie an der Reihe. Umgekehrt für Bids. Notwendig heisst nicht
    hinreichend: auch ein erreichbarer Preis kann storniert worden sein.
    """
    highest_ask = max(b.best_ask for b in books)
    lowest_bid = min(b.best_bid for b in books)

    out: list[Reduction] = []
    for step in range(len(books) - 1):
        for side in ("ask", "bid"):
            old = books[step].asks if side == "ask" else books[step].bids
            new = books[step + 1].asks if side == "ask" else books[step + 1].bids
            seen = {o.order_id: o for o in new}
            for order in old:
                match = seen.get(order.order_id)
                if match is None or match.remaining >= order.remaining - 1e-12:
                    continue
                reachable = (
                    order.price <= highest_ask if side == "ask" else order.price >= lowest_bid
                )
                out.append(
                    Reduction(
                        side=side,
                        price=order.price,
                        volume_usd=(order.remaining - match.remaining) * order.price,
                        at=step + 1,
                        reachable=reachable,
                    )
                )
    return out


def markout(books: list[Book], fills: list[Reduction], *, lag: int) -> tuple[int, float, float]:
    """Preisbewegung nach einer Verkleinerung an einem erreichbaren Preis.

    Vorzeichen aus der Sicht dessen, der die ruhende Order hatte. Ein
    gefüllter **Ask** heisst: jemand hat ihm abgekauft, er ist jetzt short.
    Steigt der Mid danach, hat er verloren. Ein gefüllter **Bid** ist der
    umgekehrte Fall. Positiv heisst hier also immer *gegen den Maker* --
    das ist adverse Selektion, in Basispunkten.

    Rückgabe: (Anzahl Ereignisse, volumengewichteter Mittelwert, einfacher
    Mittelwert). Beide, weil ein einzelner grosser Fill den gewichteten
    Wert allein bestimmen kann und das dann zu sehen sein muss.
    """
    moves: list[float] = []
    weights: list[float] = []
    for fill in fills:
        later = fill.at + lag - 1
        if later >= len(books):
            continue
        after = books[later].mid
        signed = (after - fill.price) if fill.side == "ask" else (fill.price - after)
        moves.append(10_000.0 * signed / fill.price)
        weights.append(fill.volume_usd)
    if not moves:
        return 0, float("nan"), float("nan")
    weighted = float(np.average(moves, weights=weights)) if sum(weights) > 0 else float("nan")
    return len(moves), weighted, float(np.mean(moves))


def one_market(symbol: str) -> dict[str, float] | None:
    paths = sorted(CACHE.glob(f"book_{symbol}_*.json"), key=lambda p: p.stat().st_mtime)
    if len(paths) < MIN_SNAPSHOTS:
        print(f"{symbol:6s} weniger als zwei Aufnahmen -- nichts zu vergleichen")
        return None

    books = [read_book(p) for p in paths]
    gaps = [
        (books[i + 1].received_ms - books[i].received_ms) / 1000.0 for i in range(len(books) - 1)
    ]

    ask_volume, ask_share = queue_ahead(books[0], side="ask")
    bid_volume, bid_share = queue_ahead(books[0], side="bid")

    steps = [
        transition(books[i], books[i + 1], side=side)
        for i in range(len(books) - 1)
        for side in ("ask", "bid")
    ]
    tracked = sum(s.tracked for s in steps)
    partial = sum(s.partial for s in steps)
    partial_volume = sum(s.partial_volume for s in steps)
    swept = sum(s.swept for s in steps)
    cancelled = sum(s.cancelled for s in steps)
    unchanged = sum(s.unchanged for s in steps)

    print(f"\n{symbol}  {len(books)} Aufnahmen, Abstand {np.mean(gaps):.1f}s "
          f"(min {min(gaps):.1f}, max {max(gaps):.1f})")
    print(f"  Am Antritt verfuegbar:  ask {ask_volume:>12,.0f} USD   bid {bid_volume:>12,.0f} USD")
    print(f"  1 000 USD davon:        ask {100 * ask_share:>11.3f} %   "
          f"bid {100 * bid_share:>11.3f} %")
    print(f"  Nachverfolgte Orders:   {tracked:,}")
    print(f"    unveraendert          {unchanged:>8,}  {100 * unchanged / tracked:>6.2f} %")
    print(f"    VERKLEINERT           {partial:>8,}  {100 * partial / tracked:>6.2f} %"
          f"   Volumen {partial_volume:,.0f} USD  (Fill ODER Teil-Storno)")
    print(f"    weg, Preis durch      {swept:>8,}  {100 * swept / tracked:>6.2f} %"
          f"   (Fill gefolgert, nicht belegt)")
    print(f"    weg, Preis NICHT durch{cancelled:>8,}  {100 * cancelled / tracked:>6.2f} %"
          f"   <- STORNIERT")

    print("  Unbedingte Mid-Bewegung (KEIN Markout -- bedingt auf nichts):")
    drift = mid_drift(books)
    for seconds, move in drift:
        points = len(books) - round(seconds / np.mean(gaps))
        note = "  (eine Beobachtung -- keine Schaetzung)" if points <= 1 else f"  ({points} Starts)"
        print(f"    ~{seconds:>5.1f}s  {move:>+8.3f} bp{note}")

    reductions = size_reductions(books)
    reachable = [r for r in reductions if r.reachable]
    unreachable = len(reductions) - len(reachable)
    print(
        f"  Verkleinerte Orders: {len(reductions)} -- davon {len(reachable)} an einem im\n"
        f"    Fenster ERREICHBAREN Preis, {unreachable} an einem nie erreichten\n"
        f"    (letztere koennen keine Ausfuehrung sein, nur Teil-Storno)."
    )
    print("  Markout auf den erreichbaren, positiv = GEGEN den Maker:")
    if not reachable:
        print("    keine -- nichts zu bedingen")
    for lag in range(1, len(books)):
        count, weighted, plain = markout(books, reachable, lag=lag)
        if count == 0:
            continue
        seconds = lag * float(np.mean(gaps))
        thin = "  (zu wenige fuer eine Schaetzung)" if count < MIN_FILLS else ""
        print(f"    ~{seconds:>5.1f}s  gewichtet {weighted:>+8.3f} bp   "
              f"ungewichtet {plain:>+8.3f} bp   n={count}{thin}")

    return {
        "cancel_share": cancelled / max(1, tracked),
        "partial_share": partial / max(1, tracked),
        "queue_share_ask": ask_share,
        "reachable": float(len(reachable)),
        "unreachable": float(unreachable),
        "drift_bp": drift[0][1] if drift else float("nan"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTC,ETH,SOL,XRP,LINK,DOGE")
    args = parser.parse_args()

    if not CACHE.is_dir():
        raise SystemExit(
            f"Keine Aufnahmen unter {CACHE}.\n"
            f"Zuerst scripts/study_venue_cost.py laufen lassen -- es liest nur."
        )

    print("=" * 96)
    print("E0, zweiter Schritt -- Nicht-Fills, Cancels, Warteschlange, Markouts")
    print("=" * 96)
    print(
        f"\nAus bereits aufgenommenen Buechern, ohne eine einzige Order. Uhr ist die\n"
        f"LOKALE EMPFANGSZEIT der Datei, nicht die Buchzeit der Boerse.\n"
        f"Bezugsgroesse der Warteschlange: {NOTIONAL_USD:,.0f} USD.\n"
    )

    summary: dict[str, dict[str, float]] = {}
    for symbol in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        result = one_market(symbol)
        if result is not None:
            summary[symbol] = result

    if not summary:
        raise SystemExit("Kein Markt hatte genug Aufnahmen.")

    print("\n" + "=" * 96)
    print("  Was daraus folgt")
    print("=" * 96)

    cancels = {s: v["cancel_share"] for s, v in summary.items()}
    worst = max(cancels, key=lambda s: cancels[s])
    best = min(cancels, key=lambda s: cancels[s])
    queue = {s: v["queue_share_ask"] for s, v in summary.items()}
    crowded = max(queue, key=lambda s: queue[s])

    print(
        f"\n  Storniert je ~17s-Fenster: von {100 * cancels[best]:.2f}% ({best}) bis "
        f"{100 * cancels[worst]:.2f}% ({worst}).\n"
        f"  Das ist der Anteil der Orders, die verschwinden, OHNE dass der Preis sie\n"
        f"  erreicht hat. Ein Backtest, der am Antritt zum Maker-Preis fuellt, nimmt\n"
        f"  an, dass diese Orders da bleiben. Sie bleiben nicht."
    )
    oversized = {s: v for s, v in queue.items() if v > 1.0}
    print(
        f"\n  Warteschlange am Antritt, bezogen auf {NOTIONAL_USD:,.0f} USD:\n"
        f"  Der Anteil ist Auftragsgroesse geteilt durch das Volumen am Antrittspreis.\n"
        f"  Er spannt von {100 * min(queue.values()):.2f}% bis "
        f"{100 * max(queue.values()):.2f}% ({crowded} am engsten)."
    )
    if oversized:
        names = ", ".join(f"{s} {100 * v:.0f}%" for s, v in sorted(oversized.items()))
        print(
            f"  Ueber 100% heisst: der Auftrag ist GROESSER als das ganze Antrittsniveau\n"
            f"  und kann dort gar nicht vollstaendig als Maker liegen -- {names}.\n"
            f"  Unter 100% passt er hin, steht aber hinter dem Volumen, das schon da\n"
            f"  liegt: `order_index` ordnet die Schlange, und gefuellt wird von vorn."
        )
    else:
        print(
            "  Alle unter 100%: der Auftrag passt ans Antrittsniveau, steht dort aber\n"
            "  hinter dem Volumen, das schon liegt -- gefuellt wird nach `order_index`."
        )

    reachable = {s: int(v["reachable"]) for s, v in summary.items()}
    unreachable = {s: int(v["unreachable"]) for s, v in summary.items()}
    drifts = {s: v["drift_bp"] for s, v in summary.items()}
    good = sum(reachable.values())
    bad = sum(unreachable.values())
    low = min(drifts.values())
    high = max(drifts.values())
    print(
        f"\n  Was dieses Buch NICHT hergibt: einen belegten Fill. Eine schrumpfende\n"
        f"  `remaining_base_amount` kann eine Teilausfuehrung sein oder eine\n"
        f"  Teil-Storno, und ohne Trade-Tape ist das nicht zu trennen. Dieser Lauf\n"
        f"  belegt es selbst: {bad} Verkleinerungen lagen an Preisen, die der Markt\n"
        f"  im Fenster nie erreicht hat -- die koennen keine Ausfuehrung gewesen\n"
        f"  sein. Erreichbar waren {good}, und auch die sind nur KANDIDATEN:\n"
        f"  erreichbar ist notwendig, nicht hinreichend."
    )
    print(
        f"\n  Markouts sind damit auf {good} Kandidaten gerechnet -- zu wenige fuer\n"
        f"  eine Aussage ueber adverse Selektion, und es wird keine getroffen. Zum\n"
        f"  Vergleich muss die unbedingte Mid-Bewegung daneben stehen: sie laeuft\n"
        f"  im selben Fenster zwischen {low:+.3f} und {high:+.3f} bp je ~17s. Ein\n"
        f"  Maker-Markout in dieser Groessenordnung ist derselbe Marktlauf noch\n"
        f"  einmal und kein Befund ueber die Ausfuehrung."
    )
    print(
        "\n  Und was dieser Lauf NICHT ist: fuenf Aufnahmen je Markt an einem Vormittag,\n"
        "  rund 69 Sekunden Gesamtspanne. Kein Stress, keine Tageszeiten, kein\n"
        "  Trade-Tape. Belegt ist die MESSUNG -- dass Cancel-Anteil, Warteschlange und\n"
        "  Teil-Fills aus einem Orderbuch dieser Venue ohne eigene Order ablesbar sind.\n"
        "  Die Zahlen sind eine erste Lesung. Was fehlt: ein Streaming-Collector fuer\n"
        "  1s/5s, eine Aufnahme ueber Tage fuer 5min und fuer Regime, und genug Fills\n"
        "  fuer einen Markout mit Intervall."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
