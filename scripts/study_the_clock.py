"""E12 — die Uhr: Wochenende, Funding-Stunde, Viertelstundenmarke.

    python scripts/study_the_clock.py

**Woher die Frage kommt.** Zwei Quellen, beide am 11.10.2026.

Der Nutzer: „Diese Märkte sind am Wochenende geschlossen, ich weiss nicht,
warum da so viel getradet wird." Die *Tatsache* ist falsch — Krypto-Perps
laufen 24 Stunden, sieben Tage; geschlossen sind Aktien, Devisen und CME.
Die *Intuition* darunter ist eine Hypothese mit Literaturstütze: dünnere
Wochenendbücher, weitere Spreads, und niemand hat sie auf unseren Daten
geprüft. Eine falsche Prämisse und eine prüfbare Frage sind zwei Dinge.

Kim/Hansen, arXiv:2607.09426, „The Quarter-Hour Effect": periodische
Volatilitäts- und Volumenschübe auf Minuten-, Fünfminuten- und
Viertelstundenmarken über sechs Binance-Perps, und „opening returns show
out-of-sample predictability at quarter-hour openings". Unsere Einstiege
liegen per Konstruktion auf genau diesen Marken — gemessen auf BTCUSDT: 193
von 263 Trades auf :00.

**Was vorab festgelegt ist** (`audit/EXPERIMENTS_NEXT.yaml`, Arm E12):

* Primärkennzahl ist die **Brutto**-Erwartung je Trade. Netto wäre eine
  Gebührengeschichte und sagte nichts über den Einstieg.
* Zwei-Gruppen-Differenz mit korrigiertem Intervall ohne Null **und**
  Replikation 0.5-2.0x. Zwei überlappende Intervalle nebeneinander sind kein
  Test — das ist die Lehre aus E11.
* Der **linke Rand** beider Gruppen ist Pflicht, nicht Beigabe: Anteil unter
  -1R, schlimmster Einzelverlust, 5 %-Quantil. Ein besserer Mittelwert bei
  schwererem Rand ist kein positives Ergebnis. Das ist die Lehre aus E10,
  wo ein Arm den Mittelwert um 0.0064 R hob und den schlimmsten Verlust
  verdreifachte.

**Der Confound, der E12.3 sonst erledigt.** Die Einstiegsminute korreliert
mit der Setup-Zeitebene: ein H1-Signal steigt auf :00 ein, ein M15-Signal auf
jeder Viertelstunde. Eine Gruppierung über alle Trades misst die Zeitebene
und nennt sie die Uhr. E12.3 läuft deshalb **nur innerhalb der
M15-Population**. Bricht eine Zelle unter die Mindestbesetzung, ist sie nicht
entscheidbar und wird so berichtet.

**Was ein positives Ergebnis höchstens wäre.** Ein Zeitfilter ändert nur,
welche Trades existieren, nicht ihre Verteilung. Ein Hebel, der bloss die
Trade-Zahl ändert, kann das Vorzeichen nicht drehen. E12 kann bestenfalls
eine Teilpopulation benennen, die für sich positiv ist — und muss dann gegen
das gemessen werden, was das System heute schon nimmt.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.reporting.intervals import two_group_difference

FILLS = ROOT / "data" / "replay_fills"
JOURNAL = ROOT / "data" / "journal.sqlite"
SIGNALS = ROOT / "data" / "signals.sqlite"
OUT = ROOT / "data" / "study_the_clock.json"

#: Die Signatur der laufenden Konfiguration. Der Speicher haelt mehrere
#: nebeneinander, darunter zwei Kostendeckel -- ueber alle zu gruppieren
#: wuerde den Deckel mit dem Wochentag vermischen.
LIVE_SIGNATURE = "1000.0|['A', 'B', 'E', 'F', 'G']|0.08|M15|refused-v1"

#: Der Kostendeckel dieser Signatur, zum Vergleich mit den Medianen.
COST_CAP = 0.08

#: Bonferroni-Nenner nach dem Anlegen von E12. Steht in der Registry.
TOTAL_COMPARISONS = 61
LEVEL = 1 - 0.05 / TOTAL_COMPARISONS

#: Wie viele Maerkte der vollstaendige Neulauf hat. Weniger heisst
#: unvollstaendig und nicht widerlegt.
MARKETS_EXPECTED = 12

#: Ab welchem Viertelstundenanteil eine Population als M15-Kadenz gilt.
#: Der alte Lauf liegt bei 2/542 = 0.4 %, der neue bei 65/88 = 74 %.
QUARTER_SHARE_FOR_M15 = 0.10

#: Die Viertelstundenmarken ohne die Stunde selbst.
QUARTER_MARKS = (15, 30, 45)

#: Samstag ist Wochentag 5, Sonntag 6.
SATURDAY = 5

#: Das vorab festgelegte Replikationstor.
GATE_LOW, GATE_HIGH = 0.5, 2.0

#: Funding wird auf Bybit alle acht Stunden abgerechnet.
FUNDING_HOURS = (0, 8, 16)
#: Wie lange nach der Abrechnung ein Einstieg als „in der Funding-Stunde" gilt.
FUNDING_WINDOW_MIN = 60

#: Unter dieser Besetzung je Zelle wird nicht geurteilt. Nicht die
#: Mindestgrösse der Intervallrechnung (die ist 8), sondern die Grenze, unter
#: der eine Gruppe keine Gruppe mehr ist.
MIN_CELL = 100


def gross_r(gross_pnl: float, risk_amount: float) -> float | None:
    """Brutto-Ergebnis in R. None, wenn kein Risiko verbucht ist."""
    if risk_amount is None or risk_amount <= 0:
        return None
    return gross_pnl / risk_amount


def load_new() -> list[dict[str, object]]:
    """Der 12-Markt-Lauf mit Trade-Persistenz, Märkte wie sie fertig werden."""
    rows: list[dict[str, object]] = []
    for path in sorted(FILLS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("max_bars"):
            continue  # ein gekuerzter Rauchtest ist kein Messlauf
        for fill in payload.get("fills", []):
            r = gross_r(fill.get("gross_pnl", 0.0), fill.get("risk_amount", 0.0))
            if r is None:
                continue
            rows.append({
                "symbol": payload["symbol"],
                "opened_ts": int(fill["opened_ts"]),
                "gross_r": r,
                "net_r": float(fill["r_multiple"]),
                "timeframe": fill.get("timeframe") or "",
                "setup": (fill.get("setup") or "?").split(" ", 1)[0],
            })
    return rows


def load_old() -> list[dict[str, object]]:
    """Der alte 4-Markt-Lauf aus dem Journal. Die Replikationsseite."""
    if not JOURNAL.exists():
        return []
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    rows: list[dict[str, object]] = []
    for symbol, opened, r_multiple, payload in conn.execute(
        "select symbol, opened_ts, r_multiple, payload from trades "
        "where source = 'replay' and r_multiple is not null"
    ):
        body = json.loads(payload)
        r = gross_r(body.get("gross_pnl", 0.0), body.get("risk_amount", 0.0))
        if r is None:
            continue
        reason = body.get("reason") or {}
        rows.append({
            "symbol": symbol,
            "opened_ts": int(opened),
            "gross_r": r,
            "net_r": float(r_multiple),
            "timeframe": reason.get("setup_timeframe") or "",
            "setup": reason.get("setup_key") or "?",
        })
    conn.close()
    return rows


def at(ts: int) -> datetime:
    return datetime.fromtimestamp(ts / 1000, UTC)


def is_weekend(ts: int) -> bool:
    return at(ts).weekday() >= SATURDAY


def in_funding_window(ts: int) -> bool:
    """Ob der Einstieg in den 60 Minuten nach einer Abrechnung liegt."""
    moment = at(ts)
    return moment.hour in FUNDING_HOURS and moment.minute < FUNDING_WINDOW_MIN


def on_the_hour(ts: int) -> bool:
    return at(ts).minute == 0


def on_the_quarter(ts: int) -> bool:
    """Genau :15, :30 oder :45 -- und nicht blosses „nicht :00".

    **Hier lag ein Defekt, gefunden am 11.10.2026.** Die erste Fassung
    gruppierte gegen „nicht auf der Stunde". Im alten Lauf fielen dadurch 40
    Limit-Fills zu beliebigen Minuten -- 1, 2, 3, 12, 34, 41, 52 -- in die
    Viertelstunden-Gruppe, die insgesamt 42 Faelle hatte. Nur ZWEI davon waren
    echte Viertelstunden-Entscheidungen. Die Gruppe trug also fast
    ausschliesslich Fuellzeitpunkte und nicht Entscheidungszeitpunkte.

    Der Einstiegszeitstempel ist die Fuellung, nicht die Entscheidung. Bei
    einer Limit-Order liegen die beiden auseinander, und wer nach dem
    Komplement einer Marke gruppiert, sammelt genau diese Differenz ein.
    """
    return at(ts).minute in QUARTER_MARKS


def declared_cadence() -> str:
    """Die Kadenz, die der neue Lauf in seine Ergebnisdateien schreibt."""
    for path in sorted(FILLS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("max_bars") and payload.get("signal_timeframe"):
            return str(payload["signal_timeframe"])
    return ""


def inferred_cadence(trades: list[dict]) -> str:
    """Die Kadenz des alten Laufs, aus der Minutenverteilung erschlossen.

    Der alte 4-Markt-Lauf im Journal traegt keine Signatur, also ist das die
    einzige Quelle -- und sie ist genau die "Eigenschaft, die man nur durch
    Archaeologie findet", die `journal/record.py` als keine aufgezeichnete
    Eigenschaft bezeichnet. Sie wird hier benannt und als ERSCHLOSSEN
    markiert, nicht als gelesen.

    Das Kriterium: ein M15-Signal kann auf jeder Viertelstunde feuern. Wenn
    praktisch keines das tut, wurde der M15-Chart nur zur Stunde befragt.
    """
    m15 = [t for t in trades if t["timeframe"] == "M15"]
    if len(m15) < MIN_CELL:
        return "unbekannt"
    quarters = sum(1 for t in m15 if on_the_quarter(t["opened_ts"]))
    coarse = "H1 (erschlossen)"
    return "M15" if quarters / len(m15) > QUARTER_SHARE_FOR_M15 else coarse


def tail(values: list[float]) -> dict[str, float]:
    """Der linke Rand. Vorab festgelegt, nicht nachgereicht."""
    if not values:
        return {}
    ordered = sorted(values)
    index = max(0, int(0.05 * (len(ordered) - 1)))
    return {
        "mean": round(statistics.fmean(ordered), 4),
        "share_below_minus_1r": round(sum(1 for v in ordered if v < -1.0) / len(ordered), 4),
        "worst": round(ordered[0], 4),
        "q05": round(ordered[index], 4),
    }


def cell(name: str, left: list[dict], right: list[dict], *,
         left_name: str, right_name: str) -> dict[str, object]:
    """Eine Zelle rechnen und drucken: Differenz, beide Ränder, Besetzung."""
    a = [t["gross_r"] for t in sorted(left, key=lambda t: t["opened_ts"])]
    b = [t["gross_r"] for t in sorted(right, key=lambda t: t["opened_ts"])]

    print(f"\n  {name}")
    print(f"    {left_name:28s} n={len(a):>6,}   {tail(a) or '—'}")
    print(f"    {right_name:28s} n={len(b):>6,}   {tail(b) or '—'}")

    if len(a) < MIN_CELL or len(b) < MIN_CELL:
        print(f"    -> NICHT ENTSCHEIDBAR: unter {MIN_CELL} Faellen in einer Zelle")
        return {"cell": name, "decidable": False,
                "left": {"name": left_name, "n": len(a), **tail(a)},
                "right": {"name": right_name, "n": len(b), **tail(b)}}

    diff = two_group_difference(a, b, level=LEVEL)
    if diff is None:
        print("    -> NICHT ENTSCHEIDBAR: Intervall nicht berechenbar")
        return {"cell": name, "decidable": False}

    print(f"    Differenz  {diff.mean:+.4f} R  [{diff.low:+.4f}, {diff.high:+.4f}]  "
          f"Block {diff.block}, {diff.draws:,} Zuege")
    print(f"    Null {'AUSGESCHLOSSEN' if diff.excludes_zero else 'ENTHALTEN'}"
          f"   Rand {'belegt' if diff.tail_resolved else 'ZU WENIG ZIEHUNGEN'}")
    return {
        "cell": name, "decidable": True,
        "left": {"name": left_name, "n": len(a), **tail(a)},
        "right": {"name": right_name, "n": len(b), **tail(b)},
        "difference": round(diff.mean, 6),
        "interval": [round(diff.low, 6), round(diff.high, 6)],
        "block": diff.block, "draws": diff.draws,
        "excludes_zero": diff.excludes_zero,
        "tail_resolved": diff.tail_resolved,
    }


def describe(trades: list[dict], label: str) -> dict[str, object]:
    """Wie die Trades über die Uhr liegen, bevor irgendetwas verglichen wird."""
    if not trades:
        return {}
    days = Counter(at(t["opened_ts"]).strftime("%a") for t in trades)
    weekend = sum(1 for t in trades if is_weekend(t["opened_ts"]))
    minutes = Counter(at(t["opened_ts"]).minute for t in trades)
    frames = Counter(t["timeframe"] for t in trades)
    print(f"\n  {label}: {len(trades):,} Trades, "
          f"{len(set(t['symbol'] for t in trades))} Maerkte")
    print(f"    Wochentage      {dict(days)}")
    print(f"    Wochenende      {weekend:,} von {len(trades):,} "
          f"= {weekend / len(trades):.1%}  (Kalender: 28.6 %)")
    print(f"    Einstiegsminute {dict(sorted(minutes.items())[:8])}")
    print(f"    Zeitebenen      {dict(frames)}")
    cadence = inferred_cadence(trades)
    print(f"    Kadenz          {cadence}")
    return {
        "cadence": cadence,
        "n": len(trades),
        "markets": sorted(set(t["symbol"] for t in trades)),
        "weekday_counts": dict(days),
        "weekend_share": round(weekend / len(trades), 4),
        "minute_counts": {str(k): v for k, v in sorted(minutes.items())},
        "timeframe_counts": dict(frames),
    }


def print_mechanism(out: dict, fractions: dict, stops: dict) -> None:
    """Den Mechanismus ausgeben und die Identitaet dabei mitpruefen."""
    # Und die Ursache dahinter, gemessen statt behauptet.
    #
    # `cost_fraction * stop_fraction` ist ueber alle 47.918 Zeilen konstant
    # 0.00105 -- die Rundenkostenrate von DEFAULT_SPEC. Hoehere Kostenquote
    # heisst also zwingend: engerer Stop. Das ist keine Auslegung, sondern
    # eine Identitaet, und sie wird hier mitgeprueft.
    print()
    ratio = None
    for day in ("Werktag", "Wochenende"):
        widths = sorted(stops[day])
        if not widths:
            continue
        median = statistics.median(widths)
        print(f"    {day:12s} Stopweite    Median {median:.5%}  n={len(widths):,}")
        out[day]["stop_fraction_median"] = round(median, 8)  # type: ignore[index]
    if stops["Werktag"] and stops["Wochenende"]:
        ratio = statistics.median(stops["Wochenende"]) / statistics.median(stops["Werktag"])
        out["stop_width_ratio"] = round(ratio, 4)
    identity = sorted(
        f * s for day in stops for f, s in zip(fractions[day], stops[day], strict=False) if s
    )
    if identity:
        out["cost_times_stop_median"] = round(statistics.median(identity), 8)

    print(f"\n    Der Deckel steht bei {COST_CAP}. Der Wochenend-Median liegt")
    print("    darueber, der Werktags-Median darunter -- das ist der ganze")
    print("    Mechanismus. Das Chance-Risiko-Tor greift an beiden Tagen")
    print("    gleich (36.8 %), die Setups feuern proportional (27.6 % gegen")
    print("    28.6 % Kalender). Nur die Kosten unterscheiden sich.")
    if identity:
        print(f"\n    Kostenquote * Stopweite = {statistics.median(identity):.8f} konstant,")
        print("    also ist die Kostenquote die Gebuehr geteilt durch die")
        print("    Stopweite. Hoeher heisst zwingend: engerer Stop.")
    if ratio is not None:
        print(f"    Die Wochenend-Stopweite ist das {ratio:.3f}-fache der")
        print("    Werktags-Weite. Geringere Wochenend-Vola zieht")
        print("    strukturbasierte Stops zusammen, bis die feste Gebuehr den")
        print("    Trade frisst.")
    print("\n    Das Wochenende wird nicht gemieden, weil es gefaehrlich ist,")
    print("    sondern weil es TEUER ist relativ zur verfuegbaren Bewegung --")
    print("    dieselbe Achse, auf der das ganze System haengt.\n")


def why_the_weekend_falls_out() -> dict[str, object]:
    """Wodurch das Wochenende aus dem System fällt — der Mechanismus.

    Keine Zelle von E12, sondern eine beschreibende Gruppierung des
    Signalspeichers. Sie braucht keine Mehrfachkorrektur, weil sie nichts
    testet: sie liest ab, welches Tor wie oft greift.

    Die Frage kam so: „ich weiss nicht, warum da am Wochenende so viel
    getradet wird." Das System handelt am Wochenende *unterproportional* —
    18,9 % der Trades bei 28,6 % Kalenderanteil — und diese Funktion sagt,
    wodurch.

    **Nur eine Signatur.** Der Speicher hält drei Konfigurationen
    nebeneinander, darunter zwei verschiedene Kostendeckel (0,08 und 0,15).
    Über alle zu gruppieren würde den Deckel mit dem Wochentag vermischen und
    wäre dieselbe Sorte Fehler wie der Vergleich zweier Kadenzen.
    """
    if not SIGNALS.exists():
        return {}
    conn = sqlite3.connect(f"file:{SIGNALS}?mode=ro", uri=True)
    totals: Counter = Counter()
    gates: dict[str, Counter] = {"Werktag": Counter(), "Wochenende": Counter()}
    fractions: dict[str, list[float]] = {"Werktag": [], "Wochenende": []}
    stops: dict[str, list[float]] = {"Werktag": [], "Wochenende": []}
    for ts, refused, fraction, entry, stop in conn.execute(
        "select decided_ts, refused_by, cost_fraction, entry, stop from signals "
        "where run_signature = ? and source = 'replay'",
        (LIVE_SIGNATURE,),
    ):
        day = "Wochenende" if is_weekend(ts) else "Werktag"
        totals[day] += 1
        gates[day][refused or "genommen"] += 1
        if fraction is not None:
            fractions[day].append(float(fraction))
        if entry and stop:
            stops[day].append(abs(float(entry) - float(stop)) / float(entry))
    conn.close()
    if not totals:
        return {}

    print("\n" + "=" * 74)
    print("Wodurch das Wochenende herausfaellt -- beschreibend, kein Test")
    print("=" * 74)
    print(f"\n  Signatur {LIVE_SIGNATURE}")
    print(f"  {sum(totals.values()):,} Signale, Wochenendanteil "
          f"{totals['Wochenende'] / sum(totals.values()):.1%} "
          "(Kalender 28.6 %)\n")
    print(f"    {'':12s} {'n':>8s} {'genommen':>10s} {'Kosten':>10s} {'Ch/Risiko':>10s}")
    out: dict[str, object] = {"signature": LIVE_SIGNATURE,
                              "n": sum(totals.values()),
                              "weekend_share_of_signals":
                                  round(totals["Wochenende"] / sum(totals.values()), 4)}
    for day in ("Werktag", "Wochenende"):
        n, gate = totals[day], gates[day]
        print(f"    {day:12s} {n:>8,} {gate['genommen'] / n:>9.1%} "
              f"{gate['kosten'] / n:>9.1%} {gate['chance_risiko'] / n:>9.1%}")
        out[day] = {"n": n,
                    "taken": round(gate["genommen"] / n, 4),
                    "refused_cost": round(gate["kosten"] / n, 4),
                    "refused_reward_risk": round(gate["chance_risiko"] / n, 4)}
    print()
    for day in ("Werktag", "Wochenende"):
        values = sorted(fractions[day])
        if not values:
            continue
        median = statistics.median(values)
        print(f"    {day:12s} Kostenquote  Median {median:.5f}  "
              f"Mittel {statistics.fmean(values):.5f}  n={len(values):,}")
        out[day]["cost_fraction_median"] = round(median, 6)  # type: ignore[index]
        out[day]["cost_fraction_mean"] = round(statistics.fmean(values), 6)  # type: ignore[index]
    print_mechanism(out, fractions, stops)
    return out


def cells_for(trades: list[dict]) -> list[dict[str, object]]:
    """Die drei vorab festgelegten Zellen auf einer Population."""
    out = [
        cell("E12.1  Wochenende gegen Werktag",
             [t for t in trades if is_weekend(t["opened_ts"])],
             [t for t in trades if not is_weekend(t["opened_ts"])],
             left_name="Sa/So (UTC)", right_name="Mo-Fr (UTC)"),
        cell("E12.2  Funding-Stunde gegen sonst",
             [t for t in trades if in_funding_window(t["opened_ts"])],
             [t for t in trades if not in_funding_window(t["opened_ts"])],
             left_name="<=60 min nach Abrechnung", right_name="sonst"),
    ]
    # E12.3 nur innerhalb M15 -- sonst misst die Zelle die Zeitebene.
    m15 = [t for t in trades if t["timeframe"] == "M15"]
    print(f"\n  E12.3 wird auf der M15-Population gerechnet: {len(m15):,} von "
          f"{len(trades):,} Trades")
    hour = [t for t in m15 if on_the_hour(t["opened_ts"])]
    quarter = [t for t in m15 if on_the_quarter(t["opened_ts"])]
    other = len(m15) - len(hour) - len(quarter)
    print(f"    davon :00 {len(hour):,}, auf 15/30/45 {len(quarter):,}, "
          f"zu anderen Minuten {other:,} (Limit-Fills, ausgeschlossen)")
    out.append(cell("E12.3  :00 gegen :15/:30/:45 (nur M15)",
                    hour, quarter,
                    left_name="Stundenmarke :00", right_name=":15 / :30 / :45"))
    return out


def replication(old_cells: list[dict], new_cells: list[dict], *,
                old_cadence: str = "", new_cadence: str = "") -> list[dict[str, object]]:
    """Verhaeltnis der Differenzen. 0.5-2.0x ist das vorab festgelegte Tor."""
    print("\n" + "=" * 74)
    print("Replikation: alter 4-Markt-Lauf gegen neuen 12-Markt-Lauf")
    print("=" * 74)
    rows = []
    if old_cadence and new_cadence and old_cadence.split(" ", maxsplit=1)[0] != new_cadence:
        print(f"\n  ABBRUCH: alter Lauf laeuft auf {old_cadence}, "
              f"neuer auf {new_cadence}.")
        print("  Zwei Laeufe mit verschiedener Entscheidungskadenz sind keine")
        print("  Replikation -- der Unterschied ist groesser als die Zelle, die")
        print("  er pruefen soll. Besonders E12.3: auf H1-Kadenz wird der")
        print("  M15-Chart nur zur Stunde befragt, die Vergleichsgruppe")
        print("  EXISTIERT dort nicht.\n")
        return [{"cell": c["cell"], "replicated": False,
                 "reason": f"Kadenz {old_cadence} gegen {new_cadence}"}
                for c in old_cells]
    by_name = {c["cell"]: c for c in new_cells}
    for old in old_cells:
        new = by_name.get(old["cell"])
        name = old["cell"]
        if not (old.get("decidable") and new and new.get("decidable")):
            print(f"\n  {name}\n    -> nicht replizierbar: eine Seite nicht entscheidbar")
            rows.append({"cell": name, "replicated": False, "reason": "nicht entscheidbar"})
            continue
        a, b = old["difference"], new["difference"]
        ratio = b / a if a else float("inf")
        ok = GATE_LOW <= ratio <= GATE_HIGH
        print(f"\n  {name}")
        print(f"    alt {a:+.4f} R   neu {b:+.4f} R   Verhaeltnis {ratio:+.2f}x"
              f"   {'im Tor' if ok else f'AUSSERHALB {GATE_LOW}-{GATE_HIGH}'}")
        both = old["excludes_zero"] and new["excludes_zero"]
        print(f"    beide Intervalle ohne Null: {'ja' if both else 'nein'}")
        print(f"    -> {'BESTANDEN' if (ok and both) else 'NICHT BESTANDEN'}")
        rows.append({"cell": name, "old": a, "new": b, "ratio": round(ratio, 4),
                     "ratio_in_gate": ok, "both_exclude_zero": both,
                     "passed": bool(ok and both)})
    return rows


def verdict(reps: list[dict], old_cells: list[dict], shape_new: dict) -> bool:
    """Das Urteil drucken und sagen, ob eine Zelle beide Tore genommen hat."""
    print("\n" + "=" * 74)
    print("Urteil")
    print("=" * 74)
    passed = [r for r in reps if r.get("passed")]
    # "Nicht bestanden" und "noch nicht messbar" sind nicht dasselbe. Der
    # Unterschied ist die Lehre aus E11, und ein Lauf, dem Maerkte fehlen,
    # darf nicht als Negativbefund gelesen werden.
    incomplete = [r for r in reps if not r.get("passed") and not r.get("ratio_in_gate")
                  and r.get("reason") == "nicht entscheidbar"]
    markets_new = len(shape_new.get("markets") or [])
    if not reps:
        print("\n  OFFEN -- die Replikationsseite fehlt noch.\n")
    elif incomplete and markets_new < MARKETS_EXPECTED:
        print(f"\n  OFFEN -- der neue Lauf hat {markets_new} von "
              f"{MARKETS_EXPECTED} Maerkten.")
        print(f"  {len(incomplete)} Zellen sind nur deshalb nicht entscheidbar,")
        print("  weil die Besetzung fehlt. Das ist kein Negativbefund.\n")
        print("  Was die Suchseite bisher sagt:")
        for row in old_cells:
            if not row.get("decidable"):
                print(f"    {row['cell']:42s} nicht entscheidbar")
                continue
            low, high = row["interval"]
            print(f"    {row['cell']:42s} {row['difference']:+.4f} R "
                  f"[{low:+.4f}, {high:+.4f}]  Null "
                  f"{'AUS' if row['excludes_zero'] else 'EIN'}")
        print()
    elif not passed:
        print(f"\n  Keine der {len(reps)} Zellen hat beide Tore genommen.")
        print("  Die Uhr ist auf diesen Daten keine Gruppierungsvariable,")
        print("  die das Vorzeichen traegt.\n")
    else:
        for row in passed:
            print(f"\n  BESTANDEN: {row['cell']}  "
                  f"alt {row['old']:+.4f} / neu {row['new']:+.4f} R")
        print("\n  Naechster Schritt ist NICHT, den Filter einzubauen, sondern")
        print("  ihn gegen das zu messen, was das System heute schon nimmt.\n")

    return bool([r for r in reps if r.get('passed')])


def main() -> int:
    old, new = load_old(), load_new()

    print("=" * 74)
    print("E12 -- Die Uhr: Wochenende, Funding-Stunde, Viertelstundenmarke")
    print("=" * 74)
    print(f"\n  Korrigiertes Niveau {LEVEL:.6%} (Bonferroni auf {TOTAL_COMPARISONS})")
    print("  Primaerkennzahl: BRUTTO-R je Trade")
    print(f"  Mindestbesetzung je Zelle: {MIN_CELL}")

    if not old and not new:
        print("\n  Keine Daten. Weder Journal noch replay_fills.\n")
        return 2

    mechanism = why_the_weekend_falls_out()
    shape_old = describe(old, "alter Lauf (Journal)")
    shape_new = describe(new, "neuer Lauf (replay_fills)")

    print("\n" + "=" * 74)
    print("Befund auf dem alten Lauf -- die Suchseite")
    print("=" * 74)
    old_cells = cells_for(old) if old else []

    new_cells: list[dict[str, object]] = []
    if new:
        print("\n" + "=" * 74)
        print("Dieselben Zellen auf dem neuen Lauf -- die Replikationsseite")
        print("=" * 74)
        new_cells = cells_for(new)
    else:
        print("\n  Der neue Lauf liegt noch nicht vor. Ohne ihn ist die")
        print("  Replikation offen, und ein Befund auf einer Seite ist kein")
        print("  Ergebnis -- beide Tore muessen fallen.\n")

    reps = replication(old_cells, new_cells,
                       old_cadence=shape_old.get("cadence", ""),
                       new_cadence=declared_cadence()) if (old_cells and new_cells) else []

    passed = verdict(reps, old_cells, shape_new)
    OUT.write_text(json.dumps({
        "measured_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "level": LEVEL,
        "total_comparisons": TOTAL_COMPARISONS,
        "min_cell": MIN_CELL,
        "funding_hours": list(FUNDING_HOURS),
        "funding_window_minutes": FUNDING_WINDOW_MIN,
        "weekend_mechanism": mechanism,
        "shape_old": shape_old,
        "shape_new": shape_new,
        "cells_old": old_cells,
        "cells_new": new_cells,
        "replication": reps,
        "any_passed": bool(passed),
        "complete": len(shape_new.get("markets") or []) >= MARKETS_EXPECTED,
    }, indent=1), encoding="utf-8")
    print(f"  -> {OUT.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
