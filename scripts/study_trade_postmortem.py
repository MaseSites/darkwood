"""Jeder gewonnene und jeder verlorene Trade — warum genau dieses Ergebnis.

**Der Auftrag, wörtlich:** „schaue alle verlorenen und gewonnenen trades an
finde heraus warum genau dieses ergebniss zustande gekommen ist und lerne
daraus was kannst du besser machen was kannst du weiterführen."

Dieses Skript beantwortet das an den 7.335 gespeicherten Trades. Jeder trägt
einen Nachbericht (`post_mortem`) mit `max_favourable_r`, `max_adverse_r`,
`stopped_by_wick`, `never_in_profit` und einem Urteil im Klartext, dazu den
vollständigen Entscheidungsblock (Setup, Bewertung, Regime, Klarheit,
Übereinstimmung, Konflikt).

**Was dieses Skript ausdrücklich NICHT ist: eine Filtersuche.** Wer 7.335
Trades nach zwanzig Merkmalen schneidet, findet mit Sicherheit eine Zelle, die
gut aussieht — das ist Arithmetik und kein Befund. Das Register dieses
Projekts führt `total_comparisons` und verlangt für jeden Arm ein
Bonferroni-korrigiertes Intervall **und** eine Replikation im Faktor 0,5-2,0.

Alles hier ist darum **beschreibend**: es sagt, *wie* die Trades geendet sind
und *woran* man sie unterscheiden kann. Fällt dabei ein Kandidat auf, gehört er
in `audit/EXPERIMENTS_NEXT.yaml` als Arm angemeldet und out-of-sample geprüft —
nicht hier verkündet.

    python scripts/study_trade_postmortem.py
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import numpy as np

from traidingbrain.sim.metrics import bootstrap_mean

#: Ab hier gilt ein Trade als Gewinner. Null, nicht ein Schwellenwert --
#: alles andere waere eine Entscheidung, die der Leser nicht sieht.
GEWINN = 0.0

#: Wie viele Zellen eine Aufschluesselung hoechstens zeigt.
ZELLEN = 12

#: Die zwei Schwellen, an denen ein Rueckgabe-Verlierer eingeordnet wird.
#: Benannt, weil sie eine Entscheidung sind: wer sie verschiebt, verschiebt
#: die Groesse der Eimer, und das soll sichtbar sein.
VOLL_R, HALB_R = 1.0, 0.5


def lade(root: Path) -> list[dict[str, object]]:
    eintraege: list[dict[str, object]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for j in blob.get("journal", []):
            j["symbol"] = blob["symbol"]
            eintraege.append(j)
    return eintraege


def mechanismus(j: dict[str, object]) -> str:
    """Wie dieser Trade geendet ist -- ein Etikett je Trade, sich ausschliessend.

    Die Reihenfolge ist die Pruefreihenfolge und damit eine Aussage: ein Trade,
    der liquidiert wurde, ist liquidiert, auch wenn er vorher im Plus war.
    """
    pm = j.get("post_mortem") or {}
    grund = str(j.get("exit_reason", ""))
    r = float(j.get("r_multiple", 0.0))
    if "liquidation" in grund.lower():
        return "liquidiert"
    if r > GEWINN:
        return "Ziel erreicht" if "target" in grund.lower() else f"Gewinn ohne Ziel ({grund})"
    return _verlierer(pm)


def _verlierer(pm: dict[str, object]) -> str:
    """Warum dieser Trade verloren hat -- vier sich ausschliessende Gruende.

    Getrennt von `mechanismus`, damit die Pruefreihenfolge der VERLUSTgruende
    an einer Stelle steht und beim Lesen nicht mit der Gewinnseite verwoben ist.
    """
    if pm.get("never_in_profit"):
        return "nie im Plus"
    if pm.get("stopped_by_wick"):
        return "Docht holte den Stop"
    mfe = float(pm.get("max_favourable_r") or 0.0)
    if mfe >= VOLL_R:
        return "war >= 1 R im Plus, gab zurueck"
    return (
        "war >= 0.5 R im Plus, gab zurueck"
        if mfe >= HALB_R
        else "kam nie weit ins Plus"
    )


def aufschluesseln(
    eintraege: list[dict[str, object]], schluessel: object, name: str, *, draws: int
) -> None:
    """Erwartungswert je Zelle, mit Anzahl und Intervall. Beschreibend."""
    gruppen: dict[str, list[float]] = {}
    for j in eintraege:
        try:
            k = str(schluessel(j))  # type: ignore[operator]
        except Exception:
            k = "(fehlt)"
        gruppen.setdefault(k, []).append(float(j.get("r_multiple", 0.0)))
    geordnet = sorted(gruppen.items(), key=lambda kv: -len(kv[1]))[:ZELLEN]
    print(f"\n   {name}")
    print(f"     {'Zelle':38s} {'n':>6s} {'R je Trade':>12s}  {'Anteil':>7s}")
    gesamt = len(eintraege)
    for k, werte in geordnet:
        iv = bootstrap_mean(np.array(werte, dtype=float), samples=draws)
        marke = " *" if iv.excludes_zero else ""
        print(
            f"     {k[:38]:38s} {len(werte):6,} {iv.value:+8.4f} R   "
            f"{len(werte)/gesamt:6.1%}{marke}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--draws", type=int, default=20_000)
    args = parser.parse_args(argv)

    eintraege = lade(args.fills)
    if not eintraege:
        print(f"keine Journaleintraege unter {args.fills}")
        return 2
    r = np.array([float(j.get("r_multiple", 0.0)) for j in eintraege], dtype=float)
    gewinner = [j for j in eintraege if float(j.get("r_multiple", 0.0)) > GEWINN]
    verlierer = [j for j in eintraege if float(j.get("r_multiple", 0.0)) <= GEWINN]

    print(f"{len(eintraege):,} Trades, Erwartungswert {r.mean():+.4f} R")
    print(
        f"  Gewinner {len(gewinner):,} ({len(gewinner)/len(eintraege):.1%})   "
        f"Verlierer {len(verlierer):,} ({len(verlierer)/len(eintraege):.1%})"
    )

    # -- 1. Wohin das Geld geht -------------------------------------------- #
    print("\n1. WOHIN DAS GELD GEHT -- die Zerlegung")
    brutto = sum(float(j.get("gross_pnl", 0.0)) for j in eintraege)
    gebuehr = sum(float(j.get("fees", 0.0)) for j in eintraege)
    funding = sum(float(j.get("funding", 0.0)) for j in eintraege)
    netto = sum(float(j.get("net_pnl", 0.0)) for j in eintraege)
    risiko = sum(float(j.get("risk_amount", 0.0)) for j in eintraege)
    print(f"   brutto   {brutto:+12,.2f} USDT   = {brutto/risiko:+.4f} R je Trade")
    print(f"   Gebuehr  {-gebuehr:+12,.2f} USDT   = {-gebuehr/risiko:+.4f} R")
    print(f"   Funding  {funding:+12,.2f} USDT   = {funding/risiko:+.4f} R")
    print(f"   netto    {netto:+12,.2f} USDT   = {netto/risiko:+.4f} R")
    print(
        "\n   Der Bruttoteil ist das, was die EINSTIEGE verdienen. Ist er nahe\n"
        "   null, liegt das Problem nicht bei den Kosten."
    )

    # -- 2. Wie die Trades geendet sind ------------------------------------ #
    print("\n2. WIE DIE TRADES GEENDET SIND -- Mechanismus je Trade")
    mech = Counter(mechanismus(j) for j in eintraege)
    print(f"   {'Mechanismus':34s} {'n':>6s} {'Anteil':>7s} {'R je Trade':>12s} {'R gesamt':>11s}")
    for k, n in mech.most_common():
        werte = [
            float(j.get("r_multiple", 0.0)) for j in eintraege if mechanismus(j) == k
        ]
        print(
            f"   {k:34s} {n:6,} {n/len(eintraege):6.1%} "
            f"{statistics.fmean(werte):+10.4f} R {sum(werte):+10.1f}"
        )

    # -- 3. Was die Gewinner von den Verlierern trennt --------------------- #
    print("\n3. WORAN MAN SIE UNTERSCHEIDEN KANN (beschreibend, kein Filter)")
    for name, hol in (
        (
            "Wie weit ins Plus (max_favourable_r)",
            lambda j: (j.get("post_mortem") or {}).get("max_favourable_r"),
        ),
        (
            "Wie weit ins Minus (max_adverse_r)",
            lambda j: (j.get("post_mortem") or {}).get("max_adverse_r"),
        ),
        ("Gehaltene Kerzen (bars_held)", lambda j: (j.get("post_mortem") or {}).get("bars_held")),
        ("Bewertung (rating)", lambda j: (j.get("reason") or {}).get("rating")),
        ("Stopweite in Prozent", lambda j: (j.get("reason") or {}).get("stop_distance_pct")),
    ):
        g = [float(hol(j) or 0.0) for j in gewinner]
        v = [float(hol(j) or 0.0) for j in verlierer]
        if not g or not v:
            continue
        print(
            f"   {name:38s} Gewinner {statistics.fmean(g):8.3f}   "
            f"Verlierer {statistics.fmean(v):8.3f}"
        )

    # -- 4. Aufschluesselungen --------------------------------------------- #
    print("\n4. ERWARTUNGSWERT JE ZELLE  (* = Intervall ohne Null, UNKORRIGIERT)")
    for name, hol in (
        ("Setup", lambda j: (j.get("reason") or {}).get("setup_key")),
        ("Regime", lambda j: (j.get("reason") or {}).get("regime")),
        ("Bewertungsband", lambda j: (j.get("reason") or {}).get("rating_band")),
        ("Setup-Zeitebene", lambda j: (j.get("reason") or {}).get("setup_timeframe")),
        ("Richtung", lambda j: (j.get("reason") or {}).get("side")),
        ("Markt", lambda j: j.get("symbol")),
    ):
        aufschluesseln(eintraege, hol, name, draws=args.draws)

    print(
        "\nWARNUNG ZUR LESART. Die Sterne oben sind UNKORRIGIERT. Bei dieser\n"
        "Zahl von Zellen sind einige davon reiner Zufall -- das Register\n"
        "verlangt ein Bonferroni-korrigiertes Intervall UND eine Replikation\n"
        "im Faktor 0,5-2,0. Eine Zelle, die hier glaenzt, ist ein KANDIDAT fuer\n"
        "eine Anmeldung, kein Befund. Dieses Projekt hat genau diesen Fehler\n"
        "schon zweimal bezahlt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
