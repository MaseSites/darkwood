"""Das letzte Feld einer Laufsignatur: der Kontozusatz, EINMAL zerlegt.

`scripts/plantrade.signatur_zusatz()` erzeugt ihn::

    plan30x7        Konto "plan", 30 % Margin, Hebel 7
    plan30x7r15     dazu ein Risikodeckel von 1.5 %
    plan30x7r15f    dazu geloeste Verlustbremsen

**Warum das ein eigenes Modul ist.** Am 20.10.2026 bekam der Zusatz sein `f`.
Zwei Stellen zerlegten ihn bis dahin von Hand mit `split("r")` und `float()`,
und beide liefen auf `float("15f")`:

  * `api/terminal._regel` -- das Dashboard startete nicht mehr.
  * `scripts/handelsbuch.py` -- das Handelsbuch brach ab.

Die zweite fiel erst auf, nachdem die erste behoben war. Ein Format, das
waechst, braucht EINEN Parser, der Unbekanntes stehen laesst, statt dreier,
die annehmen, sie kennten das letzte Zeichen.

Dieses Modul wird vom Entscheidungspfad NICHT importiert und bewegt den
Entscheidungsstempel darum nicht.
"""

from __future__ import annotations

import re
from typing import NamedTuple

#: Name, Marginanteil, "x", Hebel, optional Deckel und das Zeichen fuer
#: geloeste Verlustbremsen. Was nicht passt, ist kein Kontozusatz -- ein
#: Konfigurationsfeld wie `cap5` oder `refused-v1` faellt hier korrekt durch.
MUSTER = re.compile(
    r"^(?P<konto>[a-z]+)(?P<anteil>\d+)x(?P<hebel>[\d.]+)"
    r"(?:r(?P<deckel>[\d.]+))?(?P<frei>f)?$"
)


class Zusatz(NamedTuple):
    """Was in einem Kontozusatz steht. `konto` leer heisst: keiner."""

    konto: str
    anteil_pct: float
    hebel: float
    deckel_pct: float | None
    bremsen_frei: bool


def lies(signatur: str | None) -> Zusatz | None:
    """Zerlegt das letzte Feld einer Signatur, oder None, wenn es keiner ist."""
    if not signatur:
        return None
    treffer = MUSTER.match(signatur.rsplit("|", 1)[-1])
    if treffer is None:
        return None
    deckel = treffer["deckel"]
    return Zusatz(
        konto=treffer["konto"],
        anteil_pct=float(treffer["anteil"]),
        hebel=float(treffer["hebel"]),
        # Der Deckel steht in Promille-Zehnteln: `r15` sind 1.5 %.
        deckel_pct=(float(deckel) / 10.0) if deckel else None,
        bremsen_frei=bool(treffer["frei"]),
    )


def etikett(signatur: str | None) -> str:
    """Kurzform fuer die Anzeige: `30%x7 · Deckel 1.5% · Bremsen frei`."""
    z = lies(signatur)
    if z is None:
        return "?"
    teile = [f"{z.anteil_pct:g}%x{z.hebel:g}"]
    if z.deckel_pct is not None:
        teile.append(f"Deckel {z.deckel_pct:g}%")
    if z.bremsen_frei:
        teile.append("Bremsen frei")
    return " · ".join(teile)


def regel_lang(signatur: str | None) -> str:
    """Ausgeschrieben, fuer das Handelsbuch."""
    z = lies(signatur)
    if z is None:
        return (signatur or "").rsplit("|", 1)[-1] or "unbekannt"
    teile = [f"{z.anteil_pct:g} % x {z.hebel:g}"]
    teile.append(f"Deckel {z.deckel_pct:g} %" if z.deckel_pct is not None else "ohne Deckel")
    if z.bremsen_frei:
        teile.append("Verlustbremsen gelockert")
    return ", ".join(teile)
