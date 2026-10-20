"""Den Replay fuer E17 auf EINEM Codestand ueber alle 68 Maerkte fahren.

**Warum ueberhaupt neu gerechnet wird, obwohl zwoelf Maerkte schon vorliegen.**
Die zwoelf gesehenen Fills in `data/replay_fills/` stammen vom 11.10. mit
`decision_version e218664b39c8`. Der gestrandete Unseen-Lauf vom 15.10. trug
`d8c7f12104e4`, der heutige Stand traegt `0311ffba621b`. Das sind DREI
verschiedene Entscheidungscodes, und eine der Aenderungen dazwischen ist nicht
kosmetisch: das CRV-Tor entschied vorher per Gleitkomma und verwarf dabei
Signale, die exakt auf der Schwelle lagen (`risk/schwellen.py`, +16.2 % Trades).

Eine Messung, die In-Sample von einem Codestand und Out-of-Sample von einem
anderen nimmt, kann einen Unterschied nicht mehr dem MARKT zuordnen -- er
koennte vom Code kommen. Das Register verbietet das ausdruecklich: "Ein
Ergebnis auf Daten unbekannter oder gemischter Herkunft ist keine Messung."
Darum laufen beide Haelften neu, auf demselben Stand.

**Die Legacy-Daten werden nicht angefasst.** Ausgabe nach
`data/replay_fills_0311/`. `data/replay_fills/` bleibt, wie es ist.

**Wiederaufnahme ist eingebaut, und zwar im aufgerufenen Skript.**
`replay_all_markets.py` ueberspringt jeden Markt, dessen Ausgabedatei schon
existiert. Ein Neustart nach Standby oder Absturz rechnet also dort weiter, wo
er aufgehoert hat, statt von vorn. Das ist der Grund, warum dieser Lauf unter
die Aufgabenplanung mit Neustartschleife gehoert: am 19.10. ist eine
Elf-Stunden-Erhebung als Sitzungskind gestorben, und dieser Lauf dauert
laenger.

    python scripts/e17_neulauf.py --starten
    python scripts/e17_neulauf.py --stand
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
REPLAY = ROOT / "scripts" / "replay_all_markets.py"
LISTE = ROOT / "data" / "e17_maerkte.txt"
ZIEL = ROOT / "data" / "replay_fills_0311"
LOGS = ROOT / "data" / "dienst"

#: Vier und nicht neun. Am 13.10. liefen neun Engine-Prozesse gleichzeitig und
#: es war KEIN Verlangsamen, sondern eine Schwelle: sechs Stunden mit null
#: fertigen Laeufen, weil die Maschine auslagerte. Vier Prozesse bei knapp
#: 14 GB freiem Speicher lassen Luft fuer Haendler, Dashboards und Aufnahme.
STRAENGE = 4


def maerkte() -> list[str]:
    return [z.strip() for z in LISTE.read_text().splitlines() if z.strip()]


def offen() -> list[str]:
    """Was noch fehlt. Die Wiederaufnahme haengt allein an dieser Liste."""
    return [m for m in maerkte() if not (ZIEL / f"{m}.json").exists()]


def schichten(rest: list[str], n: int) -> list[list[str]]:
    """Reihum verteilen, nicht am Stueck.

    Die Laufzeit streut stark (gemessen 1.189 s bis 2.122 s je Markt, ohne den
    ausgelagerten Ausreisser). Ein Block am Stueck wuerde einen Strang mit den
    langsamen Maerkten beladen; reihum verteilt sich das von selbst.
    """
    eimer: list[list[str]] = [[] for _ in range(n)]
    for i, m in enumerate(rest):
        eimer[i % n].append(m)
    return [e for e in eimer if e]


def starten() -> int:
    ZIEL.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    rest = offen()
    if not rest:
        print(f"  Nichts offen: alle {len(maerkte())} Maerkte liegen in {ZIEL.name}.")
        return 0

    teile = schichten(rest, STRAENGE)
    print(f"  {len(rest)} von {len(maerkte())} Maerkten offen, {len(teile)} Straenge.")

    laeufe = []
    for i, teil in enumerate(teile):
        log = LOGS / f"e17_strang{i}.log"
        fh = log.open("a", encoding="utf-8")
        fh.write(f"\n=== Start {time.strftime('%d.%m %H:%M:%S')}, {len(teil)} Maerkte ===\n")
        fh.flush()
        p = subprocess.Popen(
            [str(PYTHON), "-I", "-u", str(REPLAY),
             "--symbols", ",".join(teil), "--out", str(ZIEL)],
            cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
        )
        laeufe.append((p, fh, i, len(teil)))
        print(f"    Strang {i}: {len(teil):>2} Maerkte, PID {p.pid}, Log {log.name}")

    schlecht = 0
    for p, fh, i, n in laeufe:
        rc = p.wait()
        fh.close()
        print(f"    Strang {i} ({n} Maerkte) endete mit {rc}")
        if rc != 0:
            schlecht += 1

    noch = offen()
    print(f"\n  Fertig: {len(maerkte()) - len(noch)}/{len(maerkte())} Maerkte.")
    if noch:
        # Rueckgabewert != 0, damit die Neustartschleife es noch einmal
        # versucht. Beim naechsten Anlauf sind die fertigen uebersprungen.
        print(f"  Noch offen: {len(noch)} -> {', '.join(noch[:8])}{' ...' if len(noch) > 8 else ''}")
        return 1
    return 0


def stand() -> int:
    alle, noch = maerkte(), offen()
    fertig = len(alle) - len(noch)
    print(f"  {fertig}/{len(alle)} Maerkte gerechnet ({fertig / len(alle) * 100:.0f} %)")
    if noch:
        print(f"  offen: {', '.join(noch[:12])}{' ...' if len(noch) > 12 else ''}")
    for i in range(STRAENGE):
        log = LOGS / f"e17_strang{i}.log"
        if not log.exists():
            continue
        zeilen = [z for z in log.read_text(encoding="utf-8", errors="replace").splitlines() if z.strip()]
        print(f"  Strang {i}: {zeilen[-1][:96] if zeilen else '(leer)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--starten", action="store_true", help="Die Straenge starten und warten.")
    p.add_argument("--stand", action="store_true", help="Fortschritt zeigen.")
    a = p.parse_args(argv)
    if a.stand:
        return stand()
    if a.starten:
        return starten()
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
