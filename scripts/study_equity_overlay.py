"""Regeln auf der Kapitalkurve — kann eine davon den Gewinn sichern?

**Die Frage, wörtlich gestellt:** „schaue das wir nach den knapp 10000 nicht
verlieren sondern mehr gewinnen."

Der Lauf, der die Frage ausgelöst hat: 1.000 CHF, 30 % Margin bei 7x Hebel, auf
die echten 7.335 Trades. Das Konto erreichte nach 410 Trades **9.695,41 CHF**
(9,70x) und war nach 787 Trades bei 8,85 — vollständig weg.

Eine Regel auf der Kapitalkurve verändert die Einstiege nicht. Sie steuert nur,
**wann und wie viel** Kapital exponiert ist. Damit kann sie den Erwartungswert
je Trade nicht positiv machen — aber sie kann den *Pfad* begrenzen, und genau
danach ist gefragt.

---

## Das Erfolgskriterium, VOR der Messung festgelegt

Eine Regel gilt hier als erfolgreich, wenn **alle drei** zutreffen:

1. Der **Median-Endstand über 2.000 Umordnungen** liegt über 1,0x. Nicht der
   beste Pfad, nicht der echte Pfad — der Median über Umordnungen. Ein Pfad ist
   Glück, und der echte Pfad ist der, den ich schon gesehen habe.
2. Sie schlägt die Regel **ohne Überlagerung** in mindestens 75 % der
   Umordnungen.
3. Der Anteil der Umordnungen, die den Kontoboden treffen, liegt unter 5 %.

**Warum die Umordnungen der Kern sind.** Eine Regel, die auf einen bekannten
Hoechststand zugeschnitten ist, glänzt auf *diesem* Pfad und fällt auf jedem
anderen. Die Umordnungen sind das Instrument, das genau das aufdeckt — und ohne
sie wäre jede Messung hier wertlos, weil ich die Kurve bereits kenne.

Die Regeln selbst sind **blind entworfen** worden: von vier unabhängigen
Agenten, die die Verteilungskennzahlen kannten, aber weder den Kurvenverlauf
noch den Zeitpunkt des Hoechststands.

    python scripts/study_equity_overlay.py
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

#: Wartungsmarge, wie im Spec-Schnappschuss.
MMR = 0.005

#: Unter diesem Rest ist das Konto handlungsunfaehig.
BODEN = 0.01

#: Die Vorgaben des Auftrags.
START, BASIS_ANTEIL, BASIS_HEBEL = 1_000.0, 0.30, 7.0

#: Die drei Schwellen des Erfolgskriteriums, oben begruendet.
MIN_MEDIAN, MIN_SCHLAEGT_BASIS, MAX_BODEN = 1.0, 0.75, 0.05


@dataclasses.dataclass(frozen=True, slots=True)
class Zustand:
    """Was eine Regel sehen darf -- und nur das.

    Ausdruecklich NICHT darin: der kuenftige Trade, sein R, sein Stopabstand.
    Eine Regel, die danach greifen koennte, waere Hellseherei und keine Politik.
    """

    konto: float
    hoch: float
    start: float
    trade_nr: int
    letzte_r: tuple[float, ...]
    festgeschrieben: float

    @property
    def rueckgang(self) -> float:
        return 1.0 - self.konto / self.hoch if self.hoch > 0 else 0.0

    @property
    def vielfaches(self) -> float:
        return (self.konto + self.festgeschrieben) / self.start


#: Eine Regel: aus dem Zustand werden Margin-Anteil, Hebel und der GESCHUETZTE
#: Betrag -- oder None, wenn dieser Trade ausgelassen wird.
#:
#: Der dritte Wert ist der Teil des Kontos, der nicht exponiert wird. Die Margin
#: wird aus `(konto - geschuetzt)` gerechnet, nicht aus dem ganzen Konto. Damit
#: laesst sich eine Ratsche ueberhaupt ausdruecken -- ohne ihn waere "einen
#: Gewinn festschreiben" nicht formulierbar, und das ist genau die Familie, nach
#: der der Auftrag fragt.
Regel = Callable[[Zustand], "tuple[float, float, float] | None"]


def lade(root: Path) -> tuple[np.ndarray, np.ndarray]:
    """R und Stopabstand als Preisanteil, in Zeitordnung ueber alle Maerkte."""
    zeilen: list[tuple[int, float, float]] = []
    for path in sorted(root.glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8"))["fills"]:
            e, q = float(row["entry_price"]), float(row["qty"])
            if e <= 0 or q <= 0:
                continue
            zeilen.append(
                (int(row["opened_ts"]), float(row["r_multiple"]),
                 (float(row["risk_amount"]) / q) / e)
            )
    zeilen.sort()
    return (
        np.array([z[1] for z in zeilen]),
        np.array([z[2] for z in zeilen]),
    )


def laufe(
    r: np.ndarray, stop: np.ndarray, regel: Regel, *, start: float = START
) -> tuple[float, float, int, int]:
    """Ein Durchlauf. Gibt (Endstand inkl. Festgeschriebenem, Hoch, Boden-Index, uebersprungen)."""
    konto = start
    hoch = start
    fest = 0.0
    boden = -1
    uebersprungen = 0
    letzte: list[float] = []
    for i in range(r.size):
        if konto <= start * BODEN:
            boden = i
            break
        z = Zustand(
            konto=konto, hoch=hoch, start=start, trade_nr=i,
            letzte_r=tuple(letzte[-20:]), festgeschrieben=fest,
        )
        wahl = regel(z)
        if wahl is None:
            uebersprungen += 1
            letzte.append(0.0)
            continue
        anteil, hebel, geschuetzt = wahl
        # Der geschuetzte Teil ist gebunden und wird nicht exponiert. Er bleibt
        # im Konto -- eine Ratsche legt Geld beiseite, sie verbrennt es nicht.
        fest = min(max(geschuetzt, 0.0), konto)
        handelbar = konto - fest
        if anteil <= 0 or hebel <= 0 or handelbar <= 0:
            uebersprungen += 1
            letzte.append(0.0)
            continue
        margin = handelbar * anteil
        nominal = margin * hebel
        liq = max(1.0 / hebel - MMR, 0.0)
        # Boerse schliesst zuerst, wenn der Stop jenseits der Liquidation liegt.
        liquidiert = r[i] < 0 and stop[i] > liq
        schritt = -margin if liquidiert else nominal * stop[i] * r[i]
        konto = max(konto + schritt, 0.0)
        hoch = max(hoch, konto)
        letzte.append(float(r[i]))
    return konto, hoch, boden, uebersprungen


# --------------------------------------------------------------------------- #
# Die Grundregel, gegen die alles gemessen wird
# --------------------------------------------------------------------------- #


def ohne_ueberlagerung(z: Zustand) -> tuple[float, float, float] | None:
    """Immer gleich gross -- genau das, was der Auftrag heute beschreibt."""
    return (BASIS_ANTEIL, BASIS_HEBEL, 0.0)


def alles_in_cash(z: Zustand) -> tuple[float, float, float] | None:
    """Gar nicht handeln. Die ehrlichste Vergleichsgroesse, die es gibt."""
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--umordnungen", type=int, default=2_000)
    args = parser.parse_args(argv)

    r, stop = lade(args.fills)
    print(f"{r.size:,} Trades, Erwartungswert {r.mean():+.4f} R\n")
    print("ERFOLGSKRITERIUM, VOR DER MESSUNG FESTGELEGT:")
    print(f"  1. Median-Endstand ueber {args.umordnungen:,} Umordnungen > {MIN_MEDIAN:.1f}x")
    print(f"  2. schlaegt die Basis in >= {MIN_SCHLAEGT_BASIS:.0%} der Umordnungen")
    print(f"  3. Kontoboden in < {MAX_BODEN:.0%} der Umordnungen\n")

    from traidingbrain.learn.overlays import REGELN  # noqa: PLC0415

    # Fabriken, nicht fertige Regeln -- eine zustandsbehaftete Regel darf
    # ihren Zustand nicht in den naechsten Durchlauf tragen. Siehe den
    # Kommentar an REGELN; der Fehler hat zwei Ratschen-Zeilen erfunden.
    fabriken: list[tuple[str, object]] = [
        ("ohne Ueberlagerung (Basis)", lambda: ohne_ueberlagerung),
        ("gar nicht handeln (Cash)", lambda: alles_in_cash),
        *REGELN,
    ]

    rng = np.random.default_rng(7)
    ordnungen = [rng.permutation(r.size) for _ in range(args.umordnungen)]

    basis_enden: np.ndarray | None = None
    print(f"{'Regel':34s} {'echter Pfad':>12s} {'Median':>9s} {'5.':>8s} "
          f"{'95.':>9s} {'>Basis':>7s} {'Boden':>6s}")
    for name, fabrik in fabriken:
        echt, _h, _b, _u = laufe(r, stop, fabrik())  # type: ignore[operator]
        enden = np.array(
            [laufe(r[o], stop[o], fabrik())[0] for o in ordnungen],  # type: ignore[operator]
            dtype=float,
        ) / START
        boeden = float(
            np.mean([
                1.0 if laufe(r[o], stop[o], fabrik())[2] >= 0 else 0.0  # type: ignore[operator]
                for o in ordnungen[:200]
            ])
        )
        if basis_enden is None:
            basis_enden = enden
            schlaegt = float("nan")
        else:
            schlaegt = float((enden > basis_enden).mean())
        print(
            f"{name[:34]:34s} {echt/START:11.4f}x {np.median(enden):8.4f}x "
            f"{np.percentile(enden,5):7.4f}x {np.percentile(enden,95):8.4f}x "
            f"{schlaegt:6.0%} {boeden:5.0%}"
        )

    print(
        "\nLESEHILFE. 'echter Pfad' ist die Zeitordnung -- die habe ich schon\n"
        "gesehen, sie zaehlt am wenigsten. Entscheidend ist der Median ueber\n"
        "die Umordnungen: eine Regel, die nur auf dem echten Pfad glaenzt, ist\n"
        "auf ihn zugeschnitten."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
