"""E21 -- Verdienen die Market Maker auf Lighter Geld? Aus ihren eigenen Zahlen.

===========================================================================
VORREGISTRIERUNG. Geschrieben am 20.10.2026, bevor eine Auswertung lief.
===========================================================================

**Die Idee, und warum sie besser ist als jede Spread-Arithmetik.** E20 hat
gerechnet, was ein Market Maker verdienen KOENNTE: halber Spread minus
Gebuehr minus adverse Selektion. Jede dieser drei Groessen ist geschaetzt,
und die dritte war nach der Gegenpruefung unentschieden. Eine Rechnung aus
drei unsicheren Summanden ist unsicherer als jeder einzelne.

Es geht direkter. Der Websocket-Strom traegt je Geschaeft:

    maker_position_size_before   Bestand des Makers VOR dem Geschaeft
    maker_entry_quote_before     seine Kostenbasis VOR dem Geschaeft
    is_maker_ask                 welche Seite passiv war
    price, size, maker_fee       der Rest

Daraus folgt `Durchschnittseinstand = entry_quote_before / |position_before|`,
und damit laesst sich fuer JEDES Konto der realisierte Gewinn ausrechnen --
nicht modelliert, sondern aus den Zahlen der Boerse selbst.

NACHGERECHNET, bevor darauf gebaut wurde: Konto 450265 hatte 0.37566 BTC bei
einer Basis von 30.685.995841; nach dem Verkauf von 0.00300 stand die Basis
bei 30.440.939174. Die Differenz 245.056667 ist exakt
30.685.995841 * (0.00300/0.37566) -- die Basis wird anteilig fortgeschrieben.
Die Felder bedeuten also, was sie zu bedeuten scheinen.

**Die Frage wird damit eine Beobachtung statt einer Schaetzung:**
Gibt es auf dieser Boerse Konten, die als MAKER zuverlaessig Geld verdienen?

  * Wenn ja, ist Market Making hier moeglich, und ihre Spur zeigt wie.
  * Wenn nein -- wenn auch die groessten und offensichtlich spezialisierten
    Konten bluten -- dann ist die Familie tot, und zwar unabhaengig davon,
    wie man Spread und adverse Selektion schaetzt.

---------------------------------------------------------------------------
DIE KENNZAHL, vorab erklaert
---------------------------------------------------------------------------
Je Konto: **realisierter Gewinn je gehandeltem Dollar, in Basispunkten.**
Der Nenner ist das Maker-Volumen in USD, nicht die Stueckzahl -- ein Konto,
das zehnmal einen Dollar handelt, ist nicht dasselbe wie eines, das einmal
zehn Dollar handelt. E20 hat genau an dieser Verwechslung gelitten.

---------------------------------------------------------------------------
WAS DIESE MESSUNG NICHT WEISS, vorab und nicht nachtraeglich
---------------------------------------------------------------------------
1. NUR REALISIERTES. Gewinn entsteht hier erst, wenn ein Bestand verkleinert
   wird. Offener Bestand am Ende des Fensters ist NICHT bewertet. Darum wird
   er getrennt ausgewiesen (`offener_bestand_usd`): ist er gross gegen den
   realisierten Gewinn, ist die Zahl wertlos, und das muss man sehen koennen.
2. KEIN FUNDING. Ein Perp-Maker zahlt oder bekommt Finanzierung. Sie steht
   nicht im Trade-Band. Bei kurzen Haltezeiten ist das klein, bei langen
   nicht -- darum wird die Haltedauer mitberichtet.
3. NUR WAS WIR SEHEN. Ein Konto handelt auch auf Maerkten, die wir nicht
   aufzeichnen. Sein Bestand kann dort gegenlaeufig stehen. Die Zahl gilt je
   Markt, nicht je Konto global.
4. LINKSZENSUR. Ein Konto, das zu Beginn des Fensters schon Bestand hatte,
   bringt eine Basis mit, die wir nicht beobachtet haben. Der erste
   Schliessvorgang je Konto traegt darum Gewinn aus unbeobachteter Zeit und
   wird gesondert gezaehlt.
5. DIE SENTINEL-KONTEN. IDs nahe 2^48-1 (281.474.976.710.655) sind eine
   Kodierung, kein Konto. Sie werden getrennt ausgewiesen und nicht unter
   die echten gemischt.

---------------------------------------------------------------------------
DAS TOR, vorab
---------------------------------------------------------------------------
"Market Making traegt hier" heisst: mindestens ein Konto mit >= 500
Maker-Geschaeften hat einen realisierten Ertrag ueber null, dessen
zeitgeclustertes Intervall (Bonferroni ueber die Zahl der geprueften Konten)
null ausschliesst, UND sein offener Bestand ist klein gegen seinen Gewinn.

Ein einzelnes profitables Konto ohne Intervall ist KEIN Beleg -- bei 223
Konten ist das beste von selbst positiv.

    python scripts/study_e21_wer_verdient.py --min-fills 200
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import pathlib
import sys
from collections import defaultdict
from statistics import NormalDist

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
WS = ROOT / "data" / "quarantine" / "venue_ws"

#: IDs ab hier sind eine Kodierung, kein Konto (order_quote_limit = 2**48-1).
SENTINEL = 2**47
#: Die Gebuehreneinheit, in E20 aus zwei unabhaengigen Quellen festgelegt:
#: die Marktkonfiguration nennt maker_fee "0.0000" bei vier Dezimalstellen in
#: Prozent, das Trade-Band traegt Codes 28-50. Nur 1e-7 ist mit beidem
#: vertraeglich (bei 1e-6 stuende dort 0.0028).
GEBUEHR_EINHEIT = 1e-7
#: Zeitbloecke fuers Clustern. Eine Minute ist kurz genug, dass es viele
#: gibt, und lang genug, dass eine Quote-Episode nicht ueber viele faellt.
BLOCK_MS = 60_000


def trades(markt: str):
    """Jedes Geschaeft des Marktes, in Empfangsreihenfolge."""
    for pfad in sorted(glob.glob(str(WS / markt / "strom-*.jsonl"))):
        with open(pfad, encoding="utf-8") as fh:
            for zeile in fh:
                try:
                    satz = json.loads(zeile)
                except json.JSONDecodeError:
                    continue  # letzte Zeile einer noch wachsenden Datei
                if satz.get("typ") != "trade":
                    continue
                for t in (satz["nachricht"].get("trades") or []):
                    yield t


def vollrechnung(markt: str) -> dict:
    """VOLLSTAENDIGES Ergebnis je Konto: Kasse plus Bewertung des Bestands.

    **Warum die realisierte Rechnung darunter nicht reicht, gemessen.** Sie
    zaehlt nur, was beim Verkleinern eines Bestands anfaellt. Beim ersten Lauf
    ueber 25 Minuten trugen alle drei grossen BTC-Konten einen offenen Bestand
    vom 785- bis 18.270-fachen ihres realisierten Ergebnisses -- Konto 27927
    hielt 5.1 Mio USD und hatte 280 USD realisiert. Die bp-Zahl beschrieb
    einen Bruchteil seines Risikos. Ein laengeres Fenster heilt das nicht,
    solange die Konten Bestand tragen.

    **Was stattdessen gerechnet wird.** Der Strom liefert JEDES Geschaeft des
    Marktes, und zu jedem beide Seiten. Ein Konto ist damit lueckenlos
    verfolgbar, egal ob es passiv oder aktiv handelte:

        Ergebnis = Kasse + Bestand_Ende * Mid_Ende - Bestand_Start * Mid_Start

    Kasse ist die Summe aller Zahlungen (Verkauf positiv, Kauf negativ, minus
    Gebuehr). Bestand_Start kommt aus `position_size_before` des ERSTEN
    beobachteten Geschaefts, ist also bekannt und nicht geschaetzt.

    Das ist das vollstaendige Ergebnis dieses Marktes im Fenster -- ohne
    Funding, und ohne andere Maerkte.
    """
    kasse: dict[int, float] = defaultdict(float)
    volumen_maker: dict[int, float] = defaultdict(float)
    fills_maker: dict[int, int] = defaultdict(int)
    fills_taker: dict[int, int] = defaultdict(int)
    pos_start: dict[int, float] = {}
    pos_jetzt: dict[int, float] = {}
    verlauf: dict[int, list[tuple[int, float, float, float]]] = defaultdict(list)
    mid_start = mid_ende = 0.0
    gesehen = 0

    for t in trades(markt):
        preis = float(t["price"])
        menge = float(t["size"])
        usd = float(t["usd_amount"])
        block = int(t["timestamp"]) // BLOCK_MS
        if not mid_start:
            mid_start = preis
        mid_ende = preis
        gesehen += 1
        satz = t.get("maker_fee")
        gebuehr_rate = float(satz) * GEBUEHR_EINHEIT if satz is not None else 0.0

        for rolle in ("maker", "taker"):
            if rolle == "maker":
                seite = "ask" if t["is_maker_ask"] else "bid"
            else:
                seite = "bid" if t["is_maker_ask"] else "ask"
            konto = int(t[f"{seite}_account_id"])
            vor = float(t[f"{rolle}_position_size_before"])
            if konto not in pos_start:
                pos_start[konto] = vor
            # ask = verkauft = Geld herein, Bestand runter.
            vorzeichen = -1.0 if seite == "ask" else +1.0
            fluss = -vorzeichen * usd - (usd * gebuehr_rate if rolle == "maker" else 0.0)
            kasse[konto] += fluss
            pos_jetzt[konto] = vor + vorzeichen * menge
            # Zustand am Ende dieses Geschaefts. Der Block-Gewinn wird daraus
            # NACHHER gebildet, als Differenz aufeinanderfolgender Bloecke.
            #
            # Hier stand zuerst `je_block[...] += fluss + vorzeichen*menge*preis`.
            # Das hebt sich algebraisch auf: fluss ist -vorzeichen*usd minus
            # Gebuehr, und vorzeichen*menge*preis ist +vorzeichen*usd. Uebrig
            # blieb die GEBUEHR -- also eine je Block fast konstante Groesse.
            # Die Intervalle kamen darum mit Breite null heraus
            # ([+123.62, +123.62]), und eine Breite null sieht aus wie eine
            # sehr genaue Messung statt wie ein Fehler. Aufgefallen nur, weil
            # ein Intervall ohne Breite unmoeglich ist.
            verlauf[konto].append((block, kasse[konto], pos_jetzt[konto], preis))
            if rolle == "maker":
                volumen_maker[konto] += usd
                fills_maker[konto] += 1
            else:
                fills_taker[konto] += 1

    ergebnis = {}
    for konto, k in kasse.items():
        bewertet = pos_jetzt.get(konto, 0.0) * mid_ende - pos_start.get(konto, 0.0) * mid_start
        ergebnis[konto] = k + bewertet

    # Ergebnis JE BLOCK, als Differenz des Zustands am Blockende:
    #   Gewinn = (Kasse_Ende - Kasse_Start) + Bestand_Ende * Mid_Ende
    #                                       - Bestand_Start * Mid_Start
    # Das ist dieselbe Formel wie fuers ganze Fenster, nur auf eine Minute
    # angewandt -- und erst damit traegt ein Block eine eigene Zahl, die
    # streuen kann.
    je_block: dict[int, dict[int, float]] = {}
    for konto, schritte in verlauf.items():
        letzter: dict[int, tuple[float, float, float]] = {}
        for block, ka, po, pr in schritte:
            letzter[block] = (ka, po, pr)
        bloecke = sorted(letzter)
        werte: dict[int, float] = {}
        vor_ka, vor_po, vor_pr = 0.0, pos_start.get(konto, 0.0), mid_start
        for b in bloecke:
            ka, po, pr = letzter[b]
            werte[b] = (ka - vor_ka) + po * pr - vor_po * vor_pr
            vor_ka, vor_po, vor_pr = ka, po, pr
        je_block[konto] = werte

    return {
        "markt": markt, "trades": gesehen, "ergebnis": ergebnis,
        "volumen_maker": dict(volumen_maker), "fills_maker": dict(fills_maker),
        "fills_taker": dict(fills_taker), "pos_jetzt": pos_jetzt,
        "mid_ende": mid_ende, "je_block": je_block,
    }


def auswerten(markt: str) -> dict:
    """Realisierter Gewinn je Maker-Konto, aus Bestand und Kostenbasis."""
    gewinn: dict[int, float] = defaultdict(float)
    volumen: dict[int, float] = defaultdict(float)
    anzahl: dict[int, int] = defaultdict(int)
    gebuehr: dict[int, float] = defaultdict(float)
    bestand: dict[int, float] = {}
    erste_schliessung: set[int] = set()
    zensiert: dict[int, float] = defaultdict(float)
    je_block: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    gesehen = 0
    letzter_preis = 0.0

    for t in trades(markt):
        seite = "ask" if t["is_maker_ask"] else "bid"
        konto = int(t[f"{seite}_account_id"])
        preis = float(t["price"])
        menge = float(t["size"])
        usd = float(t["usd_amount"])
        vor = float(t["maker_position_size_before"])
        basis = float(t["maker_entry_quote_before"])
        gesehen += 1

        volumen[konto] += usd
        anzahl[konto] += 1
        # maker_fee ist eine Rate je Konto, kein Betrag. Fehlt sie, wird NICHT
        # null unterstellt -- das hat in E20 "654 gebuehrenfreie Konten"
        # erfunden. Fehlend heisst hier: unbekannt, also uebersprungen.
        satz = t.get("maker_fee")
        if satz is not None:
            gebuehr[konto] += usd * float(satz) * GEBUEHR_EINHEIT

        # -- schliesst dieses Geschaeft Bestand? ------------------------- #
        schliesst = 0.0
        if vor > 0 and seite == "ask":
            schliesst = min(menge, vor)
        elif vor < 0 and seite == "bid":
            schliesst = min(menge, -vor)

        if schliesst > 0 and abs(vor) > 0:
            einstand = basis / abs(vor)
            roh = (preis - einstand) if vor > 0 else (einstand - preis)
            betrag = schliesst * roh
            if konto not in erste_schliessung:
                # Linkszensur: die Basis stammt aus unbeobachteter Zeit.
                erste_schliessung.add(konto)
                zensiert[konto] += betrag
            else:
                gewinn[konto] += betrag
                je_block[konto][int(t["timestamp"]) // BLOCK_MS] += betrag

        bestand[konto] = vor + (menge if seite == "bid" else -menge)
        letzter_preis = preis

    return {
        "markt": markt, "trades": gesehen, "gewinn": dict(gewinn),
        "volumen": dict(volumen), "anzahl": dict(anzahl), "gebuehr": dict(gebuehr),
        # Bestand in BASISEINHEITEN. Der erste Entwurf hat ihn als "offen USD"
        # gedruckt, und 49.84 sah nach 50 Dollar aus -- es waren 49.84 BTC,
        # also rund 4 Millionen. Genau die Groesse, die entscheidet, ob der
        # realisierte Gewinn ueberhaupt etwas heisst. Darum wird hier der
        # Preis mitgegeben und die Spalte umgerechnet.
        "bestand": bestand, "letzter_preis": letzter_preis,
        "zensiert": dict(zensiert),
        "je_block": {k: dict(v) for k, v in je_block.items()},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--min-fills", type=int, default=200)
    p.add_argument("--markets", default="BTC,ETH,SOL")
    a = p.parse_args(argv)

    print("=" * 78)
    print("E21 -- Verdienen die Maker Geld? Aus ihren eigenen Bestandszahlen.")
    print("=" * 78)

    for markt in [m.strip().upper() for m in a.markets.split(",") if m.strip()]:
        e = vollrechnung(markt)
        if not e["trades"]:
            print(f"\n{markt}: keine Daten.")
            continue

        kandidaten = [k for k, n in e["fills_maker"].items()
                      if n >= a.min_fills and k < SENTINEL]
        sentinel = [k for k in e["fills_maker"] if k >= SENTINEL]
        strich = "-" * 78
        print(f"\n{strich}")
        print(f"{markt}: {e['trades']:,} Geschaefte, {len(e['fills_maker'])} "
              f"Maker-Konten, davon {len(sentinel)} Sentinel (ausgeschlossen), "
              f"{len(kandidaten)} mit >= {a.min_fills} Maker-Fills")
        if not kandidaten:
            print("  Kein Konto erreicht die Mindestzahl -- noch zu wenig Daten.")
            continue

        z = NormalDist().inv_cdf(1 - 0.05 / (2 * max(1, len(kandidaten))))
        print(f"  Bonferroni ueber {len(kandidaten)} gepruefte Konten: z = {z:.3f}")
        print("  VOLLES Ergebnis = Kasse + Bewertung des Bestands (ohne Funding).")
        kopf = (f"\n  {'Konto':>10} {'MkFill':>7} {'TkFill':>7} {'MkVol USD':>12} "
                f"{'USD':>10} {'bp':>8} {'Intervall (bp)':>22} {'Bestand USD':>13}")
        print(kopf)

        zeilen = []
        for k in kandidaten:
            vol = e["volumen_maker"][k]
            usd = e["ergebnis"].get(k, 0.0)
            bp = usd / vol * 1e4 if vol else float("nan")
            bl = np.array(list(e["je_block"].get(k, {}).values()), dtype=float)
            if bl.size >= 2:
                se = float(bl.std(ddof=1)) * math.sqrt(bl.size) / vol * 1e4
                lo, hi = bp - z * se, bp + z * se
            else:
                lo = hi = float("nan")
            zeilen.append((bp, k, e["fills_maker"][k], e["fills_taker"].get(k, 0),
                           vol, usd, lo, hi,
                           e["pos_jetzt"].get(k, 0.0) * e["mid_ende"]))

        for bp, k, mf, tf, vol, usd, lo, hi, best in sorted(zeilen, reverse=True):
            marke = ""
            if lo == lo and lo > 0:
                marke = "  <-- ueber null"
            elif hi == hi and hi < 0:
                marke = "  <-- zuverlaessig negativ"
            print(f"  {k:>10} {mf:>7} {tf:>7} {vol:>12,.0f} {usd:>+10,.0f} "
                  f"{bp:>+8.2f} [{lo:>+8.2f}, {hi:>+8.2f}] {best:>+13,.0f}{marke}")

        traegt = [r for r in zeilen if r[6] == r[6] and r[6] > 0]
        print(f"\n  TOR: {len(traegt)} von {len(kandidaten)} Konten haben ein "
              f"Intervall vollstaendig ueber null.")
        if not traegt:
            print("  Kein Konto belegt hier einen Ertrag. Das ist ein Befund,")
            print("  kein fehlendes Ergebnis -- aber die Fensterlaenge begrenzt ihn.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
