"""Woran das Plankonto Geld verloren hat — zerlegt, nicht erzählt.

**Was diese Datei darf und was nicht.** Sie zerlegt einen bestehenden Verlust
in Beiträge, die sich addieren. Sie sucht KEINEN Filter, der die Verlierer
entfernt: bei zwanzig Trades findet man immer einen, und er beschreibt dann
diese zwanzig und nichts sonst. Jede Zahl hier ist eine Beschreibung der
Vergangenheit; wo sie zu einer Empfehlung wird, steht dabei, worauf die sich
stützt — auf diese Stichprobe oder auf eine frühere, grössere Messung.

Aufruf:

    python scripts/verlustanalyse.py [--konto plan]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.journal.history import konto_schluessel  # noqa: E402

JOURNAL = ROOT / "data" / "journal.sqlite"
SIGNALE = ROOT / "data" / "signals.sqlite"

#: Der Kostendeckel der Replay-Ära, auf die Live-Basis skaliert.
#: Faktor 1.05, weil die Quote exakt linear in der Rundenrate ist.
KOSTENDECKEL = 0.08
LIVE_SKALA = 1.05


def lade(konto: str) -> list[dict]:
    db = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    try:
        roh = db.execute(
            "SELECT symbol, opened_ts, closed_ts, net_pnl, r_multiple, payload "
            "FROM trades WHERE source='live' AND closed_ts IS NOT NULL "
            "ORDER BY closed_ts"
        ).fetchall()
    finally:
        db.close()

    raus = []
    for symbol, auf, zu, pnl, r, payload in roh:
        d = json.loads(payload) if payload else {}
        _, zusatz = konto_schluessel(str(d.get("run_signature") or ""))
        if zusatz != konto:
            continue
        grund = d.get("reason") or {}
        pm = d.get("post_mortem") or {}
        raus.append({
            "symbol": symbol, "auf": auf, "zu": zu,
            "pnl": float(pnl or 0.0), "r": float(r or 0.0),
            "setup": grund.get("setup_key") or "?",
            "seite": str(grund.get("side") or "").lower(),
            "stop_pct": float(grund.get("stop_distance_pct") or 0.0),
            "crv": float(grund.get("reward_risk") or 0.0),
            "rating": int(grund.get("rating") or 0),
            "konflikt": float(grund.get("conflict") or 0.0),
            "risiko": float(d.get("risk_amount") or 0.0),
            "gebuehren": float(d.get("fees") or 0.0),
            "funding": float(d.get("funding") or 0.0),
            "hebel": float(d.get("leverage") or 0.0),
            "menge": float(d.get("qty") or 0.0),
            "einstieg": float(d.get("entry_price") or 0.0),
            "mfe": float(pm.get("max_favourable_r") or 0.0),
            "mae": float(pm.get("max_adverse_r") or 0.0),
            "kerzen": int(pm.get("bars_held") or 0),
            "nie_im_plus": bool(pm.get("never_in_profit")),
            "docht": bool(pm.get("stopped_by_wick")),
            "ausstieg": str(d.get("exit_reason") or ""),
        })
    return raus


def teure_signale() -> tuple[int, int]:
    """Wie viele genommene Live-Signale das alte Kostentor abgelehnt hätte."""
    if not SIGNALE.exists():
        return (0, 0)
    db = sqlite3.connect(f"file:{SIGNALE}?mode=ro", uri=True)
    try:
        teuer = db.execute(
            "SELECT COUNT(*) FROM signals WHERE source='live' AND action='genommen' "
            "AND cost_fraction IS NOT NULL AND cost_fraction * ? > ?",
            (LIVE_SKALA, KOSTENDECKEL),
        ).fetchone()[0]
        alle = db.execute(
            "SELECT COUNT(*) FROM signals WHERE source='live' AND action='genommen'"
        ).fetchone()[0]
    finally:
        db.close()
    return (int(teuer), int(alle))


def _zeile(titel: str, wert: str) -> None:
    print(f"  {titel:<38s} {wert}")


def _block(t: str) -> None:
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--konto", default="plan")
    a = p.parse_args()

    tr = lade(a.konto)
    if not tr:
        print(f"Keine geschlossenen Trades für Konto {a.konto!r}.")
        return 1

    n = len(tr)
    gesamt = sum(t["pnl"] for t in tr)
    gewinner = [t for t in tr if t["pnl"] > 0]
    verlierer = [t for t in tr if t["pnl"] <= 0]

    _block(f"KONTO {a.konto} — {n} geschlossene Trades, {gesamt:+.2f} USD")
    _zeile("Treffer", f"{len(gewinner)}/{n} = {100*len(gewinner)/n:.0f} %")
    _zeile("Summe in R", f"{sum(t['r'] for t in tr):+.4f}")
    _zeile("Mittel in R", f"{statistics.mean(t['r'] for t in tr):+.4f}")
    _zeile("Gewinner zusammen", f"{sum(t['pnl'] for t in gewinner):+.2f} USD")
    _zeile("Verlierer zusammen", f"{sum(t['pnl'] for t in verlierer):+.2f} USD")

    # ---------------------------------------------------------------- 1
    _block("1 — DIE GRÖSSENASYMMETRIE")
    print("""  Risiko ist hier kein Eingabewert, sondern ein ERGEBNIS:

      Nominal = Kapital x Margin-Anteil x Hebel      (fest)
      Risiko  = Nominal x Stopweite                  (also proportional zur Stopweite)

  Ein Trade mit doppelt so weitem Stop riskiert doppelt so viel Geld. Wenn
  die Verlierer systematisch weitere Stops haben, verliert das Konto auch bei
  einer fairen Trefferquote.
""")
    if gewinner and verlierer:
        rg = statistics.mean(t["risiko"] for t in gewinner)
        rv = statistics.mean(t["risiko"] for t in verlierer)
        sg = statistics.mean(t["stop_pct"] for t in gewinner)
        sv = statistics.mean(t["stop_pct"] for t in verlierer)
        _zeile("Risiko je Gewinner", f"{rg:7.2f} USD")
        _zeile("Risiko je Verlierer", f"{rv:7.2f} USD   Faktor {rv/rg:.2f}x" if rg else "—")
        # `stop_distance_pct` ist BEREITS ein Prozentwert (0.9649 = 0.96 %).
        # Hier stand erst `*100`, und die Ausgabe behauptete 43 % Stopweite.
        _zeile("Stopweite Gewinner", f"{sg:7.3f} %")
        _zeile("Stopweite Verlierer", f"{sv:7.3f} %   Faktor {sv/sg:.2f}x" if sg else "—")
        print()
        # Was waere gewesen, wenn jeder Trade dasselbe Risiko getragen haette?
        mittel = statistics.mean(t["risiko"] for t in tr)
        gleich = sum(t["r"] * mittel for t in tr)
        print(f"  Gegenprobe: bei GLEICHEM Risiko ({mittel:.2f} USD je Trade) hätten")
        print(f"  dieselben R-Werte {gleich:+.2f} USD ergeben statt {gesamt:+.2f} USD.")
        print(f"  Die Asymmetrie allein kostet damit {gesamt - gleich:+.2f} USD.")
        print("""
  Das ist KEINE Hypothese über den Markt, sondern Arithmetik über die
  gespeicherten Zahlen: dieselben Trades, dieselbe Reihenfolge, nur eine
  andere Grössenregel.""")

    # ---------------------------------------------------------------- 2
    _block("2 — DIE KOSTEN")
    geb = sum(t["gebuehren"] for t in tr)
    fund = sum(t["funding"] for t in tr)
    # Gebühren sind als BETRAG gespeichert (bezahltes Geld), nicht als
    # Vorzeichen. `netto = brutto - Gebühren + Funding`, geprüft auf den Cent.
    _zeile("Gebühren bezahlt", f"{geb:.2f} USD")
    _zeile("Funding", f"{fund:+.2f} USD")
    _zeile("Anteil am Verlust", f"{100*abs(geb - fund)/abs(gesamt):.1f} %" if gesamt else "—")
    teuer, genommen = teure_signale()
    if genommen:
        print()
        _zeile("genommene Live-Signale", f"{genommen}")
        _zeile("davon über dem alten Kostentor", f"{teuer}  ({100*teuer/genommen:.0f} %)")
        print("""
  Gemessen über zwölf Märkte und 7'335 Trades: billige Trades haben die
  bessere BRUTTO-Erwartung (+0.0561 R, Intervall schliesst null aus) — nicht
  bloss weniger Abgabe. Das Kostentor war also nicht nur eine Kostenbremse.""")

    # ---------------------------------------------------------------- 3
    _block("3 — HALTEDAUER")
    for t in tr:
        t["stunden"] = (t["zu"] - t["auf"]) / 3_600_000 if t["zu"] and t["auf"] else 0.0
    kurz = [t for t in tr if t["stunden"] < 2]
    mittel_ = [t for t in tr if 2 <= t["stunden"] < 8]
    lang = [t for t in tr if t["stunden"] >= 8]
    for name, gruppe in (("unter 2 h", kurz), ("2 bis 8 h", mittel_), ("8 h und länger", lang)):
        if gruppe:
            _zeile(f"{name}", f"{len(gruppe):2d} Trades  "
                              f"{sum(x['pnl'] for x in gruppe):+8.2f} USD  "
                              f"{statistics.mean(x['r'] for x in gruppe):+.3f} R  "
                              f"{sum(1 for x in gruppe if x['pnl']>0)}/{len(gruppe)} Treffer")
        else:
            _zeile(f"{name}", "keine")
    alle_std = [t["stunden"] for t in tr]
    if alle_std:
        print()
        _zeile("Median Haltedauer", f"{statistics.median(alle_std):.2f} h")
        _zeile("längster Trade", f"{max(alle_std):.2f} h")

    # ---------------------------------------------------------------- 4
    _block("4 — GLEICHZEITIGKEIT")
    print("""  Vier Stops in einer Minute am 20.10. waren vier LONGS. Zwölf Krypto-Perps
  sind kein Portfolio aus zwölf Wetten — sie sind grösstenteils eine Wette auf
  Bitcoin. Gemessen: Beta 1.0 zu BTC, Restrendite verlässlich negativ.
""")
    fenster: dict[int, list[dict]] = defaultdict(list)
    for t in tr:
        fenster[t["auf"] // 900_000].append(t)   # 15-Minuten-Kerze
    mehrfach = {k: v for k, v in fenster.items() if len(v) > 1}
    _zeile("Kerzen mit mehr als einem Einstieg", f"{len(mehrfach)}")
    betroffene = sum(len(v) for v in mehrfach.values())
    _zeile("Trades daraus", f"{betroffene} von {n} ({100*betroffene/n:.0f} %)")
    if mehrfach:
        pnl_m = sum(t["pnl"] for v in mehrfach.values() for t in v)
        _zeile("deren Ergebnis", f"{pnl_m:+.2f} USD")
        gleichgerichtet = sum(
            1 for v in mehrfach.values()
            if len({t["seite"] for t in v}) == 1 and len(v) > 1
        )
        _zeile("davon gleichgerichtet", f"{gleichgerichtet} von {len(mehrfach)} Kerzen")

    # ---------------------------------------------------------------- 5
    _block("5 — WORAN DIE TRADES ENDETEN")
    arten: dict[str, list[dict]] = defaultdict(list)
    for t in tr:
        arten[t["ausstieg"] or "unbekannt"].append(t)
    for art, g in sorted(arten.items(), key=lambda kv: sum(x["pnl"] for x in kv[1])):
        _zeile(art, f"{len(g):2d}x  {sum(x['pnl'] for x in g):+8.2f} USD")
    print()
    _zeile("nie im Plus", f"{sum(1 for t in tr if t['nie_im_plus'])} von {n}")
    _zeile("vom Docht gestoppt", f"{sum(1 for t in tr if t['docht'])} von {n}")
    rueck = [t for t in tr if t["pnl"] < 0 and t["mfe"] >= 1.0]
    _zeile("war +1 R und gab alles zurück", f"{len(rueck)} von {n}")

    # ---------------------------------------------------------------- 6
    _block("6 — JE SETUP")
    nach: dict[str, list[dict]] = defaultdict(list)
    for t in tr:
        nach[t["setup"]].append(t)
    for s, g in sorted(nach.items(), key=lambda kv: sum(x["pnl"] for x in kv[1])):
        w = sum(1 for x in g if x["pnl"] > 0)
        _zeile(f"Setup {s}", f"{len(g):2d}x  {sum(x['pnl'] for x in g):+8.2f} USD  "
                             f"{statistics.mean(x['r'] for x in g):+.3f} R  {w}/{len(g)} Treffer")
    print("""
  Keine dieser Zeilen rechtfertigt, ein Setup abzuschalten. Setup F trug
  einmal 54 % des Gesamtverlusts über 68 Trades — das dafür aufgesetzte
  Experiment E16 fiel trotzdem (+0.0061 R, Intervall über null).""")

    _block("ZUSAMMENFASSUNG")
    # Eine Zerlegung, die AUFGEHT -- und daneben eine Gegenprobe, die als
    # solche benannt ist. Hier stand zuerst beides untereinander mit einer
    # Summenlinie darunter, und die Zahlen addierten sich nicht zum Ergebnis:
    # -78.70 + 22.03 ist nicht -139.25. Eine Summenlinie unter Posten, die
    # keine Summanden sind, ist eine erfundene Rechnung.
    brutto = sum(t["pnl"] for t in tr) + geb - fund
    print("  Was sich addiert:\n")
    print(f"    Brutto (die Richtung, bei den gelaufenen Grössen) {brutto:+9.2f} USD")
    print(f"    Gebühren                                          {-geb:+9.2f} USD")
    print(f"    Funding                                           {fund:+9.2f} USD")
    print(f"    {'-' * 54}")
    print(f"    Netto                                             {gesamt:+9.2f} USD")
    if gewinner and verlierer:
        mittel = statistics.mean(t["risiko"] for t in tr)
        gleich = sum(t["r"] * mittel for t in tr)
        print(f"""
  Gegenprobe (KEIN Summand, sondern ein anderer Lauf derselben Trades):
  mit gleichem Risiko je Trade wären aus denselben R-Werten {gleich:+.2f} USD
  geworden statt {gesamt:+.2f}. Die Grössenasymmetrie erklärt damit
  {abs(gesamt - gleich):.2f} USD = {100*abs(gesamt-gleich)/abs(gesamt):.0f} % des Verlusts.

  R ist netto gerechnet (geprüft: netto/Risiko = R auf vier Stellen), die
  Gegenprobe skaliert die Gebühren also mit — so, wie es bei einer kleineren
  Position auch wirklich wäre.""")
    print("""
  Der Rest ist die Richtung selbst, und die ist über 7'335 Trades gemessen:
  die Erwartung je Trade liegt zwischen -0.087 und +0.059 R. Kein Filter in
  dieser Datei kann daran etwas ändern; was sie zeigt, ist, wie viel von
  diesem Verlust NICHT aus der Richtung kam.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
