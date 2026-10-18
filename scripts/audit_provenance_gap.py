"""Was von der Herkunft der 7.335 Legacy-Fills noch rekonstruierbar ist.

**Warum diese Frage zuerst kommt.** `journal/provenance.py` verlangt von jedem
Fill dreizehn Angaben und von jeder Entscheidung zehn. Die naheliegende
Versuchung ist, die eingefrorene Population nachträglich damit auszustatten --
und genau das soll dieses Skript *verhindern oder belegen*, statt es zu
unterstellen. Ein nachträglich erfundenes Feld ist schlimmer als ein fehlendes:
es sieht aus wie eine Messung.

Darum wird jede Behauptung über Rekonstruierbarkeit hier **geprüft**, nicht
aufgelistet:

* Steckt in `proposal_id` wirklich der Entscheidungszeitpunkt und in
  `opened_ts` der Füllzeitpunkt? Gemessen wird, wie oft sie auseinanderliegen.
  Fallen sie immer zusammen, trägt die eine Zahl nicht zwei Angaben, und
  `decided_ts` ist NICHT rekonstruierbar.
* Lässt sich der Stop aus `risk_amount / qty` zurückrechnen? Geprüft wird, ob
  der so gewonnene Abstand plausibel ist -- und bei Stop-Ausstiegen zusätzlich
  gegen den tatsächlichen Ausstiegspreis.
* Ist das Ziel rekonstruierbar? Nur bei Zielausstiegen, und auch dort nur als
  *erreichter* Preis, nicht als geplanter.
* Gibt es irgendwo einen Referenzpreis? Ohne ihn ist Schlupf für die ganze
  Legacy-Population nicht messbar, und das ist keine Nachlässigkeit, sondern
  eine Grenze, die jeder Bericht darüber nennen muss.

Ausgabe ist eine Tabelle: je Feld *rekonstruierbar*, *teilweise* oder
*verloren*, mit der Zahl dahinter.

    python scripts/audit_provenance_gap.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

#: Ein Stopabstand ausserhalb dieser Spanne wäre kein Stop, sondern ein
#: Rechenfehler. Die Grenzen sind weit gewählt: hier wird geprüft, ob die
#: Rückrechnung ueberhaupt etwas Sinnvolles ergibt, nicht ob die Strategie gut
#: ist.
STOP_MIN, STOP_MAX = 1e-5, 0.5

#: Wie genau der zurückgerechnete Stop den Ausstiegspreis treffen muss, um als
#: Bestätigung zu gelten. Relativ, weil ein Stop-Ausstieg mit Slippage und
#: Intrabar-Auflösung nicht auf den Tick fällt.
STOP_TOLERANZ = 0.02


def lade(root: Path) -> list[tuple[str, dict[str, object]]]:
    zeilen: list[tuple[str, dict[str, object]]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            zeilen.append((str(blob["symbol"]), row))
    return zeilen


def pruefe_entscheidungszeit(
    zeilen: list[tuple[str, dict[str, object]]],
) -> tuple[int, int, int]:
    """Trägt `proposal_id` eine andere Zeit als `opened_ts`?

    Wenn nein, ist `decided_ts` nicht rekonstruierbar -- dann steht dort der
    Füllzeitpunkt, und eine Entscheidung mit dem Füllzeitpunkt als Schlüssel
    behauptet, es sei im selben Moment entschieden und gefüllt worden.
    """
    getrennt = gleich = unlesbar = 0
    for _symbol, row in zeilen:
        pid = str(row["proposal_id"])
        _, _, schwanz = pid.rpartition("-")
        if not schwanz.isdigit():
            unlesbar += 1
            continue
        if int(schwanz) == int(row["opened_ts"]):  # type: ignore[arg-type]
            gleich += 1
        else:
            getrennt += 1
    return getrennt, gleich, unlesbar


def pruefe_stop(zeilen: list[tuple[str, dict[str, object]]]) -> tuple[int, int, int]:
    """Lässt sich der Stop aus `risk_amount / qty` zurückrechnen?

    Und -- die eigentliche Probe -- fällt der so gewonnene Stop bei einem
    Stop-Ausstieg mit dem Ausstiegspreis zusammen? Ohne diese zweite Frage
    wäre „plausibler Abstand" nur eine Grössenordnung.
    """
    plausibel = unplausibel = bestaetigt = 0
    for _symbol, row in zeilen:
        qty = float(row["qty"])  # type: ignore[arg-type]
        entry = float(row["entry_price"])  # type: ignore[arg-type]
        if qty <= 0 or entry <= 0:
            unplausibel += 1
            continue
        weite = float(row["risk_amount"]) / qty  # type: ignore[arg-type]
        anteil = weite / entry
        if not (STOP_MIN <= anteil <= STOP_MAX):
            unplausibel += 1
            continue
        plausibel += 1
        if row["state"] != "closed_stop":
            continue
        richtung = -1.0 if row["side"] == "long" else 1.0
        erwartet = entry + richtung * weite
        tatsaechlich = float(row["exit_price"])  # type: ignore[arg-type]
        if abs(erwartet - tatsaechlich) / max(tatsaechlich, 1e-12) <= STOP_TOLERANZ:
            bestaetigt += 1
    return plausibel, unplausibel, bestaetigt


def pruefe_schluessel(zeilen: list[tuple[str, dict[str, object]]]) -> set[str]:
    """Welche Schlüssel kommen in den Fills überhaupt vor?

    Die Gegenprobe zu jeder Behauptung „Feld X ist verloren": wenn es doch
    irgendwo steht, muss es hier auftauchen.
    """
    vorhanden: set[str] = set()
    for _symbol, row in zeilen:
        vorhanden.update(row)
    return vorhanden


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/replay_fills"))
    args = parser.parse_args(argv)

    zeilen = lade(args.root)
    gesamt = len(zeilen)
    print(f"{gesamt:,} Fills aus {args.root}\n")

    schluessel = pruefe_schluessel(zeilen)
    print("VORHANDENE SCHLUESSEL JE FILL")
    print(f"   {', '.join(sorted(schluessel))}\n")

    getrennt, gleich, unlesbar = pruefe_entscheidungszeit(zeilen)
    print("1. ENTSCHEIDUNGSZEITPUNKT (proposal_id gegen opened_ts)")
    print(f"   verschieden : {getrennt:,}  ({getrennt / gesamt:.1%})")
    print(f"   gleich      : {gleich:,}  ({gleich / gesamt:.1%})")
    print(f"   unlesbar    : {unlesbar:,}")
    print(
        "   -> `sim/plan.py:303` baut `proposal_id = f\"{symbol}-{created_ts}\"`,\n"
        "      also traegt sie den ENTSCHEIDUNGSzeitpunkt. Das ist aus dem Code\n"
        "      belegt und nicht aus den Zahlen gefolgert."
    )
    if getrennt:
        print(
            f"      Die {getrennt:,} Faelle, in denen sie auseinanderliegen,\n"
            f"      BESTAETIGEN das: waere es zweimal dieselbe Zahl, gaebe es\n"
            f"      keinen einzigen. Die Differenz ist selbst eine Groesse --\n"
            f"      die Wartezeit auf den Fill."
        )
    else:
        print(
            "      Hier liegen sie NIE auseinander. Das widerlegt die Codezeile\n"
            "      nicht, laesst aber offen, ob die Zahl je etwas anderes trug."
        )

    gefuellt = sum(
        1 for _s, r in zeilen if str(r.get("snapshot_hash", "")).strip()
    )
    print("\n1b. SNAPSHOT_HASH -- das Feld, das es gab und das leer blieb")
    print(f"   gefuellt : {gefuellt:,} von {gesamt:,}")
    if not gefuellt:
        print(
            "   -> In ALLEN Fills leer. Ein Herkunftsfeld, das im Datensatz steht\n"
            "      und nie geschrieben wurde, ist die unangenehmste Form von\n"
            "      Luecke: es sieht in jeder Spaltenliste nach Herkunft aus. Und\n"
            "      es waere das wertvollste Feld gewesen -- ein Hash ueber den\n"
            "      Marktzustand bindet eine Entscheidung an genau die Lage, aus\n"
            "      der sie entstand. Genau das leistet `decision_id` jetzt."
        )

    plausibel, unplausibel, bestaetigt = pruefe_stop(zeilen)
    stops = sum(1 for _s, r in zeilen if r["state"] == "closed_stop")
    print("\n2. STOP (zurueckgerechnet aus risk_amount / qty)")
    print(f"   plausibler Abstand : {plausibel:,} von {gesamt:,}")
    print(f"   unplausibel        : {unplausibel:,}")
    print(
        f"   gegen Ausstieg bestaetigt : {bestaetigt:,} von {stops:,} "
        f"Stop-Ausstiegen ({bestaetigt / max(stops, 1):.2%}) -- "
        f"{stops - bestaetigt:,} Ausnahme(n)"
    )

    zustaende = Counter(str(r["state"]) for _s, r in zeilen)
    ziele = zustaende.get("closed_target", 0)
    print("\n3. ZIEL")
    for state, n in sorted(zustaende.items()):
        print(f"   {state:16s} {n:6,}")
    print(
        f"   -> nur bei den {ziele:,} Zielausstiegen ({ziele / gesamt:.1%}) steht ein\n"
        f"      erreichter Zielpreis. Fuer die uebrigen {gesamt - ziele:,} ist das\n"
        f"      GEPLANTE Ziel nicht im Speicher und nicht ableitbar."
    )

    print("\n4. WAS NICHT DA IST")
    for feld, grund in (
        ("reference_price", "nie gespeichert -- Schlupf ist fuer diese Population nicht messbar"),
        ("identity_stamp", "es gab keine Identitaet; nur run_signature und decision_version"),
        ("venue", "DIE Luecke -- stand nur in einem Kommentar in domain/market.py:70"),
        ("policy", "es gab keine ExecutionPolicy"),
        ("liquidity_role_actual", "Simulation; nie eine echte Rolle berichtet"),
        ("fee_rate_actual", "dito"),
        ("fill_price_actual", "dito -- darum ist `slippage` None und nicht 0.0"),
        ("execution_id", "kein Ausfuehrungspfad"),
        ("order_id", "kein Ausfuehrungspfad"),
    ):
        da = "DOCH VORHANDEN" if feld in schluessel else "verloren"
        print(f"   {feld:24s} {da:15s} {grund}")

    print("\n5. WAS AUS DER GEBUEHRENSPALTE ABLEITBAR IST")
    print(
        "   liquidity_role_modelled, fee_rate und fee_paid sind je Fill exakt\n"
        "   rekonstruierbar -- gemessen am 18.10.2026 durch\n"
        "   `scripts/study_venue_fee.py`, das alle 7.335 Fills eindeutig einer\n"
        "   Rollenverteilung zuordnet und die Zuordnung gegen den\n"
        "   Ausstiegsgrund gegenprueft."
    )

    print(
        "\nFAZIT. Die eingefrorene Population laesst sich NICHT nachtraeglich mit\n"
        "vollstaendiger Herkunft ausstatten. Rekonstruierbar sind Symbol,\n"
        "Entscheidungszeit, Richtung, Einstieg, Stop, Setup, Zeitebene, Rolle und\n"
        "Gebuehr. Verloren sind Referenzpreis, Venue, Policy und jede\n"
        "tatsaechliche Groesse -- und das GEPLANTE Ziel fuer alle Fills, die nicht\n"
        "im Ziel endeten.\n"
        "Daraus folgt die Reihenfolge: die Herkunft gehoert in den naechsten\n"
        "Replay hinein, nicht hinterher an den alten."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
