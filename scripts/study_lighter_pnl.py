"""Verdienen die Market Maker auf Lighter Geld? — beobachtet, nicht geschätzt.

**Warum das hier überhaupt geht.** Lighters Websocket-Strom nennt bei jedem
Geschäft BEIDE Konten (`ask_account_id`, `bid_account_id`), welche Seite der
Maker war (`is_maker_ask`) und den Bestand beider Seiten VOR dem Geschäft
(`*_position_size_before`, `*_entry_quote_before`). Damit wird eine Frage, die
sonst nur durch eigenes Risiko zu beantworten wäre, zu einer **Beobachtung**:
man sieht, ob andere damit Geld verdienen, bevor man einen Rappen einsetzt.

**Die Kennzahl ist VOLLES P&L, nicht realisiertes.** Über ein Fenster von
Stunden ist der realisierte Teil bedeutungslos neben dem offenen Bestand --
in einer früheren Messung um Faktor 785 bis 18'270. Ein Maker, der Bestand
aufbaut und ihn hält, sieht realisiert wie eine Null aus und ist in Wahrheit
long oder short unterwegs.

Gerechnet wird darum, was über das Fenster wirklich geschah:

    P&L = Σ(Geldfluss je Geschäft) + Endbestand × Endkurs − Anfangsbestand × Anfangskurs

Der Anfangsbestand wird zum Kurs seines ERSTEN beobachteten Geschäfts bewertet,
nicht zu seinem Einstandswert. Das misst, was im Fenster passiert ist, und
nicht, was jemand vorher aufgebaut hat -- eine Zahl über ein Fenster darf nicht
die Geschichte davor enthalten.

**Was diese Messung nicht kann.** Sie sieht drei Märkte. Ein Konto, das auf ETH
long und auf einem vierten Markt short steht, wird hier falsch gelesen. Darum
steht die markübergreifende Zusammenfassung daneben, und die Zahl je Konto
trägt, auf wie vielen der drei Märkte es gehandelt hat.

Aufruf:

    python scripts/study_lighter_pnl.py
    python scripts/study_lighter_pnl.py --markets ETH,SOL --min-trades 20
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STROM = ROOT / "data" / "quarantine" / "venue_ws"

#: Ab wie vielen Geschäften ein Konto überhaupt bewertet wird.
#:
#: Unter zehn ist ein P&L über Stunden fast reines Bestandsrauschen: ein
#: einziger ungeschlossener Kauf entscheidet das Vorzeichen.
MIN_GESCHAEFTE = 10

#: Ab welchem Maker-Anteil ein Konto als Maker gilt.
#:
#: Nicht 1.0: wer Bestand abbauen muss, nimmt auch mal. Die Grenze trennt
#: "stellt Preise" von "nimmt Preise", und die Auswertung zeigt sie in
#: Stufen, damit die Wahl sichtbar bleibt statt entscheidend zu sein.
MAKER_SCHWELLE = 0.80


class Konto:
    __slots__ = ("geld", "bestand", "erster_kurs", "erster_bestand",
                 "letzter_kurs", "als_maker", "als_taker", "nominal", "gebuehr_roh")

    def __init__(self) -> None:
        self.geld = 0.0
        self.bestand = 0.0
        self.erster_kurs: float | None = None
        self.erster_bestand: float | None = None
        self.letzter_kurs = 0.0
        self.als_maker = 0
        self.als_taker = 0
        self.nominal = 0.0
        self.gebuehr_roh = 0.0

    def buche(self, *, kauft: bool, menge: float, kurs: float, usd: float,
              bestand_vorher: float | None, maker: bool, gebuehr: float) -> None:
        if self.erster_kurs is None:
            self.erster_kurs = kurs
            # Der Bestand VOR dem ersten beobachteten Geschaeft ist der
            # Anfangsbestand des Fensters. Faellt das Feld aus, ist er
            # unbekannt und wird als null gefuehrt -- das ist die
            # konservative Annahme, weil sie dem Konto keinen Gewinn aus
            # einer Position zuschreibt, die wir nie gesehen haben.
            self.erster_bestand = bestand_vorher if bestand_vorher is not None else 0.0
            self.bestand = self.erster_bestand
        self.geld += -usd if kauft else usd
        self.bestand += menge if kauft else -menge
        self.letzter_kurs = kurs
        self.nominal += usd
        self.gebuehr_roh += gebuehr
        if maker:
            self.als_maker += 1
        else:
            self.als_taker += 1

    @property
    def geschaefte(self) -> int:
        return self.als_maker + self.als_taker

    @property
    def maker_anteil(self) -> float:
        return self.als_maker / self.geschaefte if self.geschaefte else 0.0

    @property
    def pnl(self) -> float:
        """Volles P&L über das Fenster: Geld plus Bestandsbewertung."""
        anfang = (self.erster_bestand or 0.0) * (self.erster_kurs or 0.0)
        return self.geld + self.bestand * self.letzter_kurs - anfang


def lies(markt: str, konten: dict[int, Konto]) -> tuple[int, float]:
    """Alle Geschäfte eines Marktes in die Konten buchen."""
    ordner = STROM / markt
    if not ordner.exists():
        return (0, 0.0)
    n = 0
    gebuehr_summe = 0.0
    for pfad in sorted(ordner.glob("strom-*.jsonl")):
        with pfad.open(encoding="utf-8", errors="replace") as f:
            for zeile in f:
                # Billiger Vorfilter: über 90 % der Zeilen sind Buchänderungen.
                if '"typ":"trade"' not in zeile:
                    continue
                try:
                    nachricht = json.loads(zeile)["nachricht"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                for t in nachricht.get("trades") or []:
                    try:
                        menge = float(t["size"])
                        kurs = float(t["price"])
                        usd = float(t["usd_amount"])
                        ask, bid = int(t["ask_account_id"]), int(t["bid_account_id"])
                        maker_ist_ask = bool(t["is_maker_ask"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    gebuehr = float(t.get("maker_fee") or 0.0)
                    gebuehr_summe += gebuehr
                    n += 1

                    # Der Verkaeufer (ask) gibt Menge ab und bekommt Geld.
                    mv = t.get("maker_position_size_before")
                    tv = t.get("taker_position_size_before")
                    ask_vorher = mv if maker_ist_ask else tv
                    bid_vorher = tv if maker_ist_ask else mv

                    konten[ask].buche(
                        kauft=False, menge=menge, kurs=kurs, usd=usd,
                        bestand_vorher=float(ask_vorher) if ask_vorher is not None else None,
                        maker=maker_ist_ask, gebuehr=gebuehr if maker_ist_ask else 0.0)
                    konten[bid].buche(
                        kauft=True, menge=menge, kurs=kurs, usd=usd,
                        bestand_vorher=float(bid_vorher) if bid_vorher is not None else None,
                        maker=not maker_ist_ask, gebuehr=gebuehr if not maker_ist_ask else 0.0)
    return (n, gebuehr_summe)



# --------------------------------------------------------------------------- #
# Die Zerlegung, ohne die das Ergebnis falsch gelesen wird
# --------------------------------------------------------------------------- #

#: Nach welchen Abständen ein Maker-Geschäft nachbewertet wird, in Sekunden.
#:
#: Das ist das Standardmass "realisierter Spread": direkt nach dem Geschäft
#: misst man, was gestellt wurde; nach Minuten misst man, wie viel davon an
#: informierten Fluss zurückgegeben wurde. Die Differenz IST die adverse
#: Selektion, und sie ist der eigentliche Preis des Market Making -- nicht
#: die Gebühr.
HORIZONTE = (0, 10, 60, 300)


def realisierter_spread(markt: str, horizonte=HORIZONTE) -> dict:
    """Was ein Maker-Geschäft nach N Sekunden wert war, über alle Maker.

    Vorzeichen: der Maker VERKAUFT (ask) → er gewinnt, wenn der Kurs fällt.
    Er KAUFT (bid) → er gewinnt, wenn der Kurs steigt. Gerechnet wird in
    Basispunkten auf das gehandelte Nominal, damit Märkte vergleichbar sind.
    """
    ordner = STROM / markt
    if not ordner.exists():
        return {}

    # Erst die Kurszeitreihe, dann die Bewertung. Zwei Durchgänge durch
    # dieselben Dateien sind billiger als alles im Speicher zu halten.
    zeit: list[int] = []
    kurs: list[float] = []
    geschaefte: list[tuple[int, float, float, bool]] = []   # ts, preis, usd, maker_verkauft

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
                        p = float(t["price"])
                        usd = float(t["usd_amount"])
                        maker_ist_ask = bool(t["is_maker_ask"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    zeit.append(ts)
                    kurs.append(p)
                    geschaefte.append((ts, p, usd, maker_ist_ask))

    if len(geschaefte) < 100:
        return {}

    paare = sorted(zip(zeit, kurs))
    zeit = [z for z, _ in paare]
    kurs = [k for _, k in paare]

    import bisect

    raus: dict[int, dict] = {}
    for h in horizonte:
        summe_bp = 0.0
        nominal = 0.0
        gezaehlt = 0
        drift_summe = 0.0
        seite_summe = 0.0
        for ts, p, usd, maker_verkauft in geschaefte:
            ziel = ts + h * 1000
            # bisect_RIGHT, nicht left. Mehrere Geschaefte teilen sich einen
            # Zeitstempel (ein Taker raeumt mehrere Ebenen ab); `left` fand
            # dann das ERSTE dieser Geschaefte und mass, wo in der Raeumung
            # dieses Geschaeft lag -- nicht, was danach geschah. Auf BTC gab
            # das bei Horizont 0 eine "Drift" von -0.39 bp, obwohl dort per
            # Konstruktion null stehen muesste.
            i = bisect.bisect_right(zeit, ziel)
            if i >= len(kurs):
                continue            # Fenster reicht nicht mehr -- weglassen,
                                    # nicht mit dem letzten Kurs auffuellen:
                                    # das waere eine Bewertung, die es nicht gibt
            p2 = kurs[i]
            # Maker verkauft: Gewinn wenn p2 < p. Maker kauft: Gewinn wenn p2 > p.
            rendite = (p - p2) / p if maker_verkauft else (p2 - p) / p
            summe_bp += rendite * usd
            # Die DRIFT ueber denselben Horizont, seitenblind. Ohne sie liest
            # man eine Marktbewegung als Handwerk: die Maker gingen in diesem
            # Fenster netto short, und der Kurs stieg -- jeder Verkauf sieht
            # dann auf jedem Horizont schlecht aus, egal wie gut er gestellt
            # war. Was uebrig bleibt, wenn man sie abzieht, ist die adverse
            # Selektion.
            drift_summe += ((p2 - p) / p) * usd
            # +1 wenn der Maker gekauft hat, -1 wenn verkauft. Der
            # nominalgewichtete Mittelwert ist das Seitenungleichgewicht,
            # und GENAU ueber dieses wirkt die Drift ins Ergebnis.
            seite_summe += (-1.0 if maker_verkauft else 1.0) * usd
            nominal += usd
            gezaehlt += 1
        if nominal:
            # Die Drift wirkt ueber das Seitenungleichgewicht ins Ergebnis:
            # sind die Maker netto Verkaeufer und steigt der Kurs, sieht
            # jedes Geschaeft auf jedem Horizont schlechter aus, egal wie gut
            # es gestellt war. Abgezogen wird darum `Ungleichgewicht x Drift`
            # und nicht die Drift selbst -- und schon gar nicht ihr Betrag,
            # wie es die erste Fassung tat.
            ungleich = seite_summe / nominal
            drift_bp = 10_000 * drift_summe / nominal
            roh_bp = 10_000 * summe_bp / nominal
            raus[h] = {
                "bp": roh_bp,
                "drift_bp": drift_bp,
                "ungleich": ungleich,
                "bereinigt_bp": roh_bp - ungleich * drift_bp,
                "usd": summe_bp,
                "nominal": nominal,
                "n": gezaehlt,
            }
    return raus


def zerlege_pnl(konten: dict, p_start: float, p_ende: float) -> dict:
    """Das Gesamt-P&L in Ausführung und Altbestand, exakt.

    Mit `pos0` als Anfangsbestand und `q_i` als vorzeichenbehafteten Mengen:

        P&L = Σ q_i·(P_ende − p_i)   +   pos0·(P_ende − P_start)
              ───────────────────       ─────────────────────────
              Ausführung                Altbestand reitet die Bewegung

    Der zweite Term hat mit Market Making NICHTS zu tun: er ist die Position,
    die das Konto beim ersten beobachteten Geschäft schon hatte, durch die
    Kursbewegung des Fensters getragen. Ihn im Ergebnis stehen zu lassen,
    heisst Richtung als Handwerk zu lesen.
    """
    aus: dict[str, float] = {"ausfuehrung": 0.0, "altbestand": 0.0, "netto_menge": 0.0}
    for k in konten.values():
        pos0 = k.erster_bestand or 0.0
        alt = pos0 * (p_ende - p_start)
        aus["altbestand"] += alt
        aus["ausfuehrung"] += k.pnl - alt
        aus["netto_menge"] += k.bestand - pos0
    return aus

def _block(t: str) -> None:
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def auswerten(konten: dict[int, Konto], titel: str, min_geschaefte: int) -> None:
    gross = [k for k in konten.values() if k.geschaefte >= min_geschaefte]
    if not gross:
        print(f"  {titel}: kein Konto mit {min_geschaefte}+ Geschäften.")
        return

    _block(titel)
    print(f"  {len(konten)} Konten gesehen, {len(gross)} mit mindestens "
          f"{min_geschaefte} Geschäften.\n")

    stufen = [(0.95, 1.01), (0.80, 0.95), (0.50, 0.80), (0.05, 0.50), (0.0, 0.05)]
    print(f"  {'Maker-Anteil':<16s} {'Konten':>7s} {'P&L zusammen':>15s} "
          f"{'Median':>11s} {'Gewinner':>10s} {'Nominal':>15s}")
    print(f"  {'-' * 78}")
    for lo, hi in stufen:
        g = [k for k in gross if lo <= k.maker_anteil < hi]
        if not g:
            continue
        pnls = [k.pnl for k in g]
        gewinner = sum(1 for p in pnls if p > 0)
        name = f"{lo:.0%}–{min(hi, 1.0):.0%}"
        print(f"  {name:<16s} {len(g):>7d} {sum(pnls):>15,.0f} "
              f"{statistics.median(pnls):>11,.0f} {gewinner:>6d}/{len(g):<3d} "
              f"{sum(k.nominal for k in g):>15,.0f}")

    maker = [k for k in gross if k.maker_anteil >= MAKER_SCHWELLE]
    taker = [k for k in gross if k.maker_anteil < 0.20]
    print()
    for name, g in (("MAKER (≥80 % gestellt)", maker), ("TAKER (<20 % gestellt)", taker)):
        if not g:
            continue
        pnls = sorted(k.pnl for k in g)
        summe = sum(pnls)
        nominal = sum(k.nominal for k in g)
        print(f"  {name}")
        print(f"     {len(g)} Konten · P&L zusammen {summe:+,.0f} USD · "
              f"Median {statistics.median(pnls):+,.0f}")
        print(f"     Gewinner {sum(1 for p in pnls if p > 0)}/{len(g)} "
              f"({100*sum(1 for p in pnls if p > 0)/len(g):.0f} %)")
        print(f"     Nominal {nominal:,.0f} USD → "
              f"{10_000*summe/nominal:+.3f} bp auf das gehandelte Nominal"
              if nominal else "")
        print(f"     Spanne: schlechtestes {pnls[0]:+,.0f} · bestes {pnls[-1]:+,.0f}")
        print()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", default="BTC,ETH,SOL")
    p.add_argument("--min-trades", type=int, default=MIN_GESCHAEFTE)
    a = p.parse_args()
    maerkte = [m.strip().upper() for m in a.markets.split(",") if m.strip()]

    gesamt: dict[int, Konto] = defaultdict(Konto)
    maerkte_je_konto: dict[int, set[str]] = defaultdict(set)
    geschaefte_gesamt = 0
    gebuehr_gesamt = 0.0
    nominal_gesamt = 0.0

    for m in maerkte:
        konten: dict[int, Konto] = defaultdict(Konto)
        n, geb = lies(m, konten)
        geschaefte_gesamt += n
        gebuehr_gesamt += geb
        nominal_gesamt += sum(k.nominal for k in konten.values()) / 2
        print(f"  {m}: {n:,} Geschäfte, {len(konten):,} Konten".replace(",", "’"))
        for kid in konten:
            maerkte_je_konto[kid].add(m)
        auswerten(konten, f"{m} — P&L je Konto über das Fenster", a.min_trades)

        # Die Zerlegung, ohne die das Ergebnis falsch gelesen wird.
        maker = {kid: k for kid, k in konten.items()
                 if k.geschaefte >= a.min_trades and k.maker_anteil >= MAKER_SCHWELLE}
        kurse = [(k.erster_kurs, k.letzter_kurs) for k in konten.values() if k.erster_kurs]
        if maker and kurse:
            p_start = min(kurse, key=lambda x: x[0])[0]
            p_ende = statistics.median([e for _, e in kurse])
            # Anfangs- und Endkurs aus den Geschaeften selbst, nicht aus einer
            # zweiten Quelle: eine Bewertung gegen einen fremden Kurs misst
            # auch den Unterschied zwischen den Quellen.
            alle = sorted((k.erster_kurs, k.letzter_kurs) for k in konten.values() if k.erster_kurs)
            p_start, p_ende = alle[0][0], alle[-1][1]
            z = zerlege_pnl(maker, p_start, p_ende)
            print(f"  ZERLEGUNG der {len(maker)} Maker-Konten "
                  f"({p_start:,.2f} → {p_ende:,.2f}, {100*(p_ende/p_start-1):+.2f} %)"
                  .replace(",", "’"))
            print(f"     Ausführung (das Handwerk)   {z['ausfuehrung']:+15,.0f} USD"
                  .replace(",", "’"))
            print(f"     Altbestand (die Richtung)   {z['altbestand']:+15,.0f} USD"
                  .replace(",", "’"))
            print(f"     Netto-Mengenänderung        {z['netto_menge']:+15,.2f} "
                  f"(Maker gingen {'LONG' if z['netto_menge'] > 0 else 'SHORT'})"
                  .replace(",", "’"))

        rs = realisierter_spread(m)
        if rs:
            print(f"\n  REALISIERTER SPREAD aller Maker-Geschäfte auf {m}:")
            print(f"     {'Horizont':<10s} {'roh (bp)':>10s} {'Drift (bp)':>12s} "
                  f"{'bereinigt':>11s} {'USD':>13s} {'Geschäfte':>11s}")
            for h, w in sorted(rs.items()):
                name = "sofort" if h == 0 else f"+{h} s"
                print(f"     {name:<10s} {w['bp']:>10.4f} {w['drift_bp']:>12.4f} "
                      f"{w['bereinigt_bp']:>11.4f} {w['usd']:>13,.0f} "
                      f"{w['n']:>11,}".replace(",", "’"))
            print("""
     Sofort ist, was gestellt wurde. Der Abfall danach IST die adverse
     Selektion -- der Teil des Spreads, der an informierten Fluss
     zurueckgeht. Nicht die Gebuehr ist der Preis des Market Making,
     sondern diese Differenz.""")
        # Fuer die Zusammenfassung die Konten je Markt getrennt halten: ein
        # Konto auf zwei Maerkten ist zwei Beobachtungen, keine Summe. Ein
        # Zusammenzaehlen ueber Maerkte waere nur richtig, wenn wir ALLE
        # Maerkte saehen -- und wir sehen drei.
        for kid, k in konten.items():
            gesamt[(kid, m)] = k   # type: ignore[index]

    if not geschaefte_gesamt:
        print("\nKeine Geschäfte gefunden. Läuft der Sammler?")
        return 1

    _block("ÜBER ALLE DREI MÄRKTE (je Konto und Markt getrennt gezählt)")
    auswerten(gesamt, "alle Märkte", a.min_trades)

    _block("WAS DIESE ZAHLEN NICHT SAGEN")
    mehrfach = sum(1 for v in maerkte_je_konto.values() if len(v) > 1)
    print(f"""  · Wir sehen DREI Märkte. {mehrfach:,} Konten handelten auf mehr als
    einem davon, und wer ausserhalb hedgt, wird hier falsch gelesen.

  · Das Fenster sind Stunden, keine Monate. Ein Maker mit offenem Bestand
    trägt dessen Kursbewegung im Ergebnis — über ein kurzes Fenster ist das
    Richtungsrisiko und nicht sein Handwerk.

  · Die Gebühr: {gebuehr_gesamt:,.0f} Einheiten auf {nominal_gesamt:,.0f} USD
    Nominal. Die EINHEIT des Feldes `maker_fee` ist aus den Daten nicht
    zweifelsfrei zu bestimmen. Unter jeder plausiblen Lesart (Mikro-Dollar
    bis Hundertstel-Basispunkte) liegt sie zwischen 0.0001 und 0.1 bp und
    damit weit unter dem gemessenen Touch-Spread von 0.46 bp auf ETH. Die
    P&L-Zahlen oben sind VOR Gebühr.

  · Ein positives Gesamtergebnis der Maker heisst nicht, dass WIR es
    wiederholen könnten: gemessen handeln nur 2.880 % des am Touch
    angebotenen Nominals (E20). Wer nicht gefüllt wird, verdient nichts.""".replace(",", "’"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
