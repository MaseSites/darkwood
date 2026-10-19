"""E19 — der Kehraus: jeder benannte Kandidat, einmal, auf dem gesperrten Teil.

**Was das ist.** Dieses Projekt hat über Wochen Dutzende Filter vorgeschlagen,
gemessen und verworfen — fast alle auf derselben Population, aus der sie
stammten. Dieses Skript nimmt *alle auf einmal*, rechnet sie auf dem
zeitlich abgetrennten letzten Drittel, und korrigiert über die Zahl der
Vergleiche. Es ist ausdrücklich eine Fischzug-Messung — aber eine, die ihr
eigenes Fischen mitzählt.

**Warum das die entscheidende Form ist.** Einzeln geprüft sieht irgendeiner
der Filter immer gut aus: bei 40 Vergleichen und einem Fünf-Prozent-Niveau
erwartet man zwei Treffer rein zufällig. Genau daran ist der bisher beste
Kandidat des Registers schon einmal gescheitert — seine eigene Notiz sagt:
*„die EINZIGE positive Zelle von 48 gedruckten — bei 48 Vergleichen erwartet
man 2,4 durch Zufall."*

**Der Vergleichsmassstab ist nicht die Null.** Ein Filter muss besser sein als
*das, was das System ohnehin nimmt*. Ein Filter, der die schlechte Hälfte
wegwirft, ist gegen null trivial besser und gegen die Grundgesamtheit
vielleicht wertlos. Dieser Fehler ist in diesem Projekt schon zweimal
gemacht worden.

**Die Kandidaten stehen in `KANDIDATEN` und werden NICHT während des Laufs
ergänzt.** Wer nach dem Ergebnis einen siebenundvierzigsten hinzufügt, hat
die Korrektur gebrochen.

    python scripts/study_e19_kehraus.py
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import sys
from collections.abc import Callable
from pathlib import Path
from statistics import NormalDist

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.domain.market import DEFAULT_SPEC

TAG_MS = 86_400_000
SEED = 20261019
ZIEHUNGEN = 10_000
MIN_N = 30

Zeile = dict[str, object]
Filter = Callable[[Zeile], bool]


def _setup(z: Zeile) -> str:
    return str(z.get("setup", "")).split(":")[0].strip()[:1]


def _tf(z: Zeile) -> str:
    return str(z.get("timeframe", "")).upper()


def _stunde(z: Zeile) -> int:
    return datetime.datetime.fromtimestamp(
        int(z["ts"]) / 1000, datetime.UTC
    ).hour


def _wochentag(z: Zeile) -> int:
    return datetime.datetime.fromtimestamp(
        int(z["ts"]) / 1000, datetime.UTC
    ).weekday()


# -- Fabriken -------------------------------------------------------------- #
#
# Die Schwellen stehen als ARGUMENT, nicht als Literal im Vergleich. Das ist
# nicht nur sauberer fuer den Linter: so steht jede Zahl genau einmal, an der
# Stelle, wo der Kandidat benannt wird, und ein Tippfehler faellt beim Lesen
# der Tabelle auf statt in einer Lambda-Zeile.

def _ist_setup(*buchstaben: str) -> Filter:
    return lambda z: _setup(z) in buchstaben


def _nicht_setup(buchstabe: str) -> Filter:
    return lambda z: _setup(z) != buchstabe


def _ist_tf(*namen: str) -> Filter:
    return lambda z: _tf(z) in namen


def _setup_auf_tf(buchstaben: tuple[str, ...], tfs: tuple[str, ...]) -> Filter:
    return lambda z: _setup(z) in buchstaben and _tf(z) in tfs


def _seite(richtung: str) -> Filter:
    return lambda z: str(z["side"]).lower() == richtung


def _kosten_hoechstens(grenze: float) -> Filter:
    return lambda z: float(z["kostenquote"]) <= grenze


def _stopweite_zwischen(unten: float, oben: float) -> Filter:
    return lambda z: unten <= float(z["stopweite"]) <= oben


def _wochentag_unter(grenze: int) -> Filter:
    return lambda z: _wochentag(z) < grenze


def _wochentag_ab(grenze: int) -> Filter:
    return lambda z: _wochentag(z) >= grenze


def _stunden(von: int, bis: int) -> Filter:
    """`von` bis `bis` in UTC. Laeuft der Bereich ueber Mitternacht, kehrt er um."""
    if von < bis:
        return lambda z: von <= _stunde(z) < bis
    return lambda z: _stunde(z) >= von or _stunde(z) < bis


def _markt_in(*namen: str) -> Filter:
    return lambda z: str(z["symbol"]) in namen


def _markt_nicht_in(*namen: str) -> Filter:
    return lambda z: str(z["symbol"]) not in namen


def _und(*teile: Filter) -> Filter:
    return lambda z: all(t(z) for t in teile)


#: Jeder Kandidat, den dieses Projekt je benannt hat. Fest, vor dem Lauf.
#:
#: Wer nach dem Ergebnis einen weiteren hinzufuegt, bricht die
#: Bonferroni-Korrektur -- sie zaehlt genau die Eintraege dieser Tabelle.
KANDIDATEN: dict[str, Filter] = {
    "nur Setup A": _ist_setup("A"),
    "nur Setup B": _ist_setup("B"),
    "nur Setup E": _ist_setup("E"),
    "nur Setup F": _ist_setup("F"),
    "nur Setup G": _ist_setup("G"),
    "ohne Setup F": _nicht_setup("F"),
    "A oder B": _ist_setup("A", "B"),

    "nur D1": _ist_tf("D1"),
    "nur H4": _ist_tf("H4"),
    "nur H1": _ist_tf("H1"),
    "nur M15": _ist_tf("M15"),
    "D1 oder H4": _ist_tf("D1", "H4"),

    "A auf D1+H4": _setup_auf_tf(("A",), ("D1", "H4")),
    "A+B auf D1+H4": _setup_auf_tf(("A", "B"), ("D1", "H4")),
    "A auf D1": _setup_auf_tf(("A",), ("D1",)),
    "A auf H4": _setup_auf_tf(("A",), ("H4",)),

    "nur Long": _seite("long"),
    "nur Short": _seite("short"),

    "Kostenquote <= 0.03": _kosten_hoechstens(0.03),
    "Kostenquote <= 0.04": _kosten_hoechstens(0.04),
    "Kostenquote <= 0.06": _kosten_hoechstens(0.06),
    "Stopweite >= 2 %": _stopweite_zwischen(0.02, 9.9),
    "Stopweite >= 3 %": _stopweite_zwischen(0.03, 9.9),
    "Stopweite 1,5-3 %": _stopweite_zwischen(0.015, 0.03),

    "Werktags": _wochentag_unter(5),
    "Wochenende": _wochentag_ab(5),
    "EU-Stunden (07-16 UTC)": _stunden(7, 16),
    "US-Stunden (13-22 UTC)": _stunden(13, 22),
    "Asien (23-08 UTC)": _stunden(23, 8),

    "nur BTC/ETH": _markt_in("BTCUSDT", "ETHUSDT"),
    "ohne BTC/ETH": _markt_nicht_in("BTCUSDT", "ETHUSDT"),

    "A auf D1+H4, Kosten <= 0.04":
        _und(_setup_auf_tf(("A",), ("D1", "H4")), _kosten_hoechstens(0.04)),
    "ohne F, Kosten <= 0.04":
        _und(_nicht_setup("F"), _kosten_hoechstens(0.04)),
    "Werktags, Kosten <= 0.04":
        _und(_wochentag_unter(5), _kosten_hoechstens(0.04)),
}


def lade(root: Path, schlupf_bps: float) -> list[Zeile]:
    c = DEFAULT_SPEC["maker_fee"] + DEFAULT_SPEC["taker_fee"] + schlupf_bps * 1e-4
    zeilen: list[Zeile] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            entry, qty = float(row["entry_price"]), float(row["qty"])
            risiko = float(row["risk_amount"])
            if entry <= 0 or qty <= 0 or risiko <= 0:
                continue
            weite = risiko / (qty * entry)
            zeilen.append({
                "symbol": blob["symbol"], "ts": int(row["opened_ts"]),
                "r": float(row["r_multiple"]), "side": row.get("side", ""),
                "setup": row.get("setup", ""), "timeframe": row.get("timeframe", ""),
                "stopweite": weite, "kostenquote": c / weite if weite > 0 else 9.9,
            })
    zeilen.sort(key=lambda z: int(z["ts"]))
    return zeilen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--auswahl-anteil", type=float, default=0.70)
    args = parser.parse_args(argv)

    cfg = load_config()
    zeilen = lade(args.fills, cfg.engine.simulation.slippage_bps)
    t0, t1 = int(zeilen[0]["ts"]), int(zeilen[-1]["ts"])
    grenze = int(t0 + (t1 - t0) * args.auswahl_anteil)
    gesperrt = [z for z in zeilen if int(z["ts"]) >= grenze]

    def tag(ms: int) -> str:
        return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%d.%m.%Y")

    k = len(KANDIDATEN)
    # Bonferroni: statt 1,96 die Normalquantile zum korrigierten Niveau.
    z_krit = NormalDist().inv_cdf(1 - 0.05 / (2 * k))

    print(f"E19 -- KEHRAUS. {k} vorher festgelegte Kandidaten, EIN Lauf.")
    print(f"Gesperrter Teil: {tag(grenze)} .. {tag(t1)}, {len(gesperrt):,} Trades")
    r_all = np.array([float(z["r"]) for z in gesperrt])
    print(f"Grundgesamtheit (was das System ohnehin nimmt): {r_all.mean():+.4f} R\n")
    print(f"Bonferroni ueber {k} Vergleiche: z = {z_krit:.3f} statt 1,960")
    print("Der Massstab ist die GRUNDGESAMTHEIT, nicht die Null.\n")

    sym = np.array([str(z["symbol"]) for z in gesperrt])
    ts = np.array([int(z["ts"]) for z in gesperrt], dtype=np.int64)
    blk = ((ts - ts.min()) // (7 * TAG_MS)).astype(int)
    paare = sorted({(s, int(b)) for s, b in zip(sym, blk, strict=True)})
    idx = {p: np.where((sym == p[0]) & (blk == p[1]))[0] for p in paare}
    rng = np.random.default_rng(SEED)
    zug = [[paare[i] for i in rng.integers(0, len(paare), len(paare))]
           for _ in range(ZIEHUNGEN)]

    return kehre(gesperrt, Pruefstand(r_all, zug, idx, z_krit, len(KANDIDATEN)))


@dataclasses.dataclass(frozen=True, slots=True)
class Pruefstand:
    """Alles, was jeder Kandidat zum Geprueftwerden braucht.

    Als ein Traeger statt sechs Argumenten: die Ziehungen sind fuer ALLE
    Kandidaten dieselben, und das ist keine Bequemlichkeit, sondern Teil der
    Methode -- vergleicht man jeden Kandidaten gegen eigene Ziehungen, misst
    man zusaetzlich den Unterschied zwischen den Ziehungen.
    """

    r: np.ndarray
    zug: list[list[tuple[str, int]]]
    idx: dict[tuple[str, int], np.ndarray]
    z_krit: float
    vergleiche: int


def kehre(gesperrt: list[Zeile], stand: Pruefstand) -> int:
    """Jeder Kandidat, einmal, mit mitgezaehlten Vergleichen."""
    r_all, zug, idx = stand.r, stand.zug, stand.idx
    z_krit, k = stand.z_krit, stand.vergleiche
    print(f"{'Kandidat':30s} {'n':>6s} {'Mittel R':>10s} {'Differenz':>11s} "
          f"{'Bonferroni-Intervall':>24s}")
    print("-" * 88)
    treffer = []
    for name, f in KANDIDATEN.items():
        maske = np.array([bool(f(z)) for z in gesperrt])
        if maske.sum() < MIN_N:
            print(f"{name:30s} {int(maske.sum()):6d}   zu wenige Trades")
            continue
        diff = float(r_all[maske].mean() - r_all.mean())
        proben = []
        for pick in zug:
            t = np.concatenate([idx[p] for p in pick])
            m = maske[t]
            if m.sum() < MIN_N:
                continue
            proben.append(r_all[t][m].mean() - r_all[t].mean())
        if len(proben) < ZIEHUNGEN // 2:
            print(f"{name:30s} {int(maske.sum()):6d}   zu instabil")
            continue
        se = float(np.std(proben, ddof=1))
        lo, hi = diff - z_krit * se, diff + z_krit * se
        best = lo > 0
        if best:
            treffer.append(name)
        print(f"{name:30s} {int(maske.sum()):6d} {r_all[maske].mean():+10.4f} "
              f"{diff:+11.4f} [{lo:+.4f}, {hi:+.4f}]{'  <<< BESTEHT' if best else ''}")

    print(f"\n{'=' * 70}")
    if treffer:
        print(f"{len(treffer)} von {k} Kandidaten bestehen die Korrektur:")
        for t in treffer:
            print(f"  {t}")
    else:
        print(f"KEINER der {k} Kandidaten besteht die Korrektur.")
        print("Die Richtungsfamilie ist damit auf dem zeitlich abgetrennten")
        print("Drittel erschoepft -- nicht nach einer Auswahl, sondern nach")
        print("einem vollstaendigen Kehraus mit mitgezaehlten Vergleichen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
