"""Halten die Berichte, was sie behaupten? Befehle und Zahlen gegen die Wirklichkeit.

    python scripts/verify_claims.py              # schnell: Befehle und Fakten
    python scripts/verify_claims.py --slow       # dazu: jedes Skript mit --help starten

**Anlass, und er ist unangenehm.** Diese Sitzung hat mehrfach falsche Zahlen in
die eigenen Berichte geschrieben:

* eine Startzeit (12:34 UTC), die nie gelesen, sondern geschrieben wurde — und
  das in einem Bericht, dessen Gegenstand ein Zeitfenster ist;
* „4 von 21 Trades geblockt" als Argument für eine Bremse, ohne nachzusehen,
  **welche** — zwei davon waren die grössten Gewinner, die Bremse hätte Geld
  gekostet;
* „die Replay-Population ist zuverlässig negativ" auf Basis einer Population,
  die ein abgeschaltetes Setup enthält und ein aktives nicht;
* eine Trade-Rate von 1,9/Tag, die aus einer alten Messung über vier Märkte
  stammte und gemessen 2,56 ist.

Jeder dieser Fehler war **nachrechenbar** und keiner ist aufgefallen, bis
jemand zufällig hinsah. 23 von 31 Berichten tragen schon einen
Reproduktionsbefehl — was fehlt, ist etwas, das ihn auch ausführt.

## Was geprüft wird

**Tier 1 — Befehle.** Jeder `Reproduktion:`-Block nennt ein Skript. Existiert
es? Lässt es sich importieren? Ein Bericht, dessen Befehl nicht mehr läuft,
ist nicht reproduzierbar, egal wie gut seine Zahlen einmal waren.

**Tier 2 — Fakten.** Eine Handvoll Zahlen, die in den Berichten als Konstanten
auftauchen und sich gegen die Daten halten lassen. Jede steht unten mit ihrer
Quelle *und* mit der Messung, die sie prüft. Wenn die Daten wachsen, wandern
manche mit — darum trägt jede Behauptung, ob sie fest oder beweglich ist.

**Was NICHT geprüft wird**, und das ehrlich: ob eine Schlussfolgerung aus
ihren Zahlen folgt. Das kann kein Skript. Dies fängt die Sorte Fehler, die
diese Sitzung tatsächlich gemacht hat — veraltete und ungelesene Zahlen —,
nicht die Sorte, die ein falsches Argument aus richtigen Zahlen baut.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.journal.version import decision_closure
from traidingbrain.strategies.guide import GuidePool

DOCS = sorted([*(ROOT / "audit").glob("*.md"), *(ROOT / "docs").glob("*.md")])
JOURNAL = ROOT / "data" / "journal.sqlite"

#: Wie weit Kontobuch und Journal auseinanderliegen duerfen. Ein Rappen,
#: weil die Rundung im Journal auf vier Dezimalstellen geht und zwei Konten
#: sich um 0,0001 unterscheiden.
BOOK_TOLERANCE = 0.01


@dataclass(frozen=True)
class Fact:
    """Eine Behauptung, die sich gegen die Daten halten lässt."""

    label: str
    where: str
    measure: Callable[[], object]
    expected: object
    fixed: bool
    """Fest: darf sich nicht ändern. Beweglich: wächst mit den Daten, dann
    ist eine Abweichung nach oben in Ordnung und nur die Richtung zählt."""


def _journal(query: str) -> object:
    if not JOURNAL.exists():
        return None
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    try:
        return conn.execute(query).fetchone()[0]
    finally:
        conn.close()


def _setups_in_journal(source: str) -> set[str]:
    if not JOURNAL.exists():
        return set()
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    try:
        where = "source = 'live'" if source == "live" else "source != 'live'"
        rows = conn.execute(
            f"SELECT payload FROM trades WHERE {where} AND closed_ts IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    out: set[str] = set()
    for (payload,) in rows:
        key = (json.loads(payload).get("reason") or {}).get("setup_key")
        if key:
            out.add(key)
    return out


def _active_setups() -> set[str]:
    return {s.key for s in GuidePool.for_config(load_config(ROOT / "config")).setups}


def _decision_closure() -> int:
    return len(decision_closure())


def _contaminated_live_signals() -> object:
    """Genommene Live-Signale, die die Replay-Gebuehr abgelehnt haette.

    **Warum diese Pruefung existiert.** `EVIDENZ_UND_RISIKO_AUDIT.md`, 3.3
    behauptet: „Die Vorwaerts-Elf sind davon nicht verunreinigt -- kein
    Live-Trade wurde genommen, den die Replay-Gebuehr abgelehnt haette."

    Das war wahr, als es geschrieben wurde, und ist am 11.10.2026 um 16:00
    UTC falsch geworden: `XRPUSDT-1791734400000` steht bei einer Kostenquote
    von 0,077440, und auf die Replay-Basis skaliert (Faktor 1,05, weil die
    Quote exakt linear in der Rundenrate ist) sind das 0,081312 gegen einen
    Deckel von 0,08. Das Signal ist zu einem Trade geworden: -1,0756 R.

    Kein Fehler des Audits -- eine Behauptung mit Verfallsdatum, die niemand
    neu geprueft hat. Genau dafuer gibt es diese Datei, und die Behauptung
    stand nicht darin. Jetzt steht sie drin, mit dem heute gemessenen Wert
    als `fixed`, damit jede Veraenderung in beide Richtungen auffaellt.
    """
    signals = ROOT / "data" / "signals.sqlite"
    if not signals.exists():
        return None
    conn = sqlite3.connect(f"file:{signals}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM signals WHERE source='live' AND action='genommen' "
            "AND cost_fraction IS NOT NULL AND cost_fraction * 1.05 > 0.08"
        ).fetchone()[0]
    finally:
        conn.close()


def _books_that_disagree() -> object:
    """Konten, deren Journal-Summe nicht zum Kontobuch passt.

    **Warum diese Pruefung existiert.** Am 11.10.2026 fiel auf, dass das
    Journal fuer BTCUSDT auf 936,1945 summiert, das Kontobuch aber 991,2427
    sagt. Die Luecke ist auf vier Dezimalstellen das Nettoergebnis einer
    einzigen Zeile, `live-BTCUSDT-1790928000000`: qty 0,06 gegen qty 0,006
    beim naechsten BTC-Trade, 49,84 USDT Risiko auf ein 1.000-USDT-Konto
    (4,98 % gegen einen Deckel von 3 %), und das Tally des Kontos zaehlt
    `opened: 1, closed: 1`. Ein Trade aus einer zerstoerten Kontogeneration.

    Elf Konten stimmten auf den Rappen, eines nicht -- und nichts hat das
    gemeldet, bis jemand die Summe gegen das Buch hielt. Die Folge war, dass
    jede Aussage ueber „die 24 Live-Trades" eine Generation mitzaehlte, die
    nicht dazugehoert, inklusive der Zielrechnung und einer Zahl des Audits,
    die dadurch um Faktor 5 zu klein war.

    Erwartet ist deshalb **1**, nicht 0: so viele weiss das Projekt heute.
    Eine zweite Abweichung ist ein neuer Befund und muss auffallen.
    """
    paper = ROOT / "data" / "paper.sqlite"
    if not (paper.exists() and JOURNAL.exists()):
        return None
    book = sqlite3.connect(f"file:{paper}?mode=ro", uri=True)
    ledger = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    try:
        config = load_config(ROOT / "config")
        start = config.engine.simulation.initial_equity
        pooled = config.risk.sizing.basis == "portfolio"

        if pooled:
            # Eine Kasse, also EIN Abgleich.
            #
            # **Und die Formel musste nachgezogen werden.** Unter `portfolio`
            # haelt jede der zwoelf Kontozeilen den GETEILTEN Stand, nicht
            # ihren eigenen. Die Zeilenpruefung von vorher verglich dann
            # 12.075 gegen 1.006 und meldete zwoelf Abweichungen statt
            # einer -- der Waisen-Trade war darin nicht mehr zu sehen,
            # sondern nur noch Rauschen aus der falschen Formel. Das hat der
            # Waechter am 13.10. selbst gemeldet, und er hatte recht: eine
            # Zahl, die nicht mehr stimmt, ist nicht halb richtig.
            #
            # Richtig ist: Startkapital aller Konten plus die Summe ALLER
            # Live-Trades gegen die geteilte Kasse. Gemessen ergibt das
            # +55,0481 -- die Waise, auf vier Dezimalstellen. Derselbe
            # Defekt, eine Pruefung statt zwoelf.
            row = book.execute("SELECT equity FROM portfolio WHERE id = 1").fetchone()
            if row is None:
                return None
            count = book.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            total = ledger.execute(
                "SELECT COALESCE(SUM(net_pnl), 0.0) FROM trades WHERE source='live'"
            ).fetchone()[0]
            expected = start * int(count) + float(total)
            return 1 if abs(float(row[0]) - expected) > BOOK_TOLERANCE else 0

        sums = {
            symbol: float(total)
            for symbol, total in ledger.execute(
                "SELECT symbol, SUM(net_pnl) FROM trades WHERE source='live' GROUP BY 1"
            )
        }
        off = 0
        for symbol, equity in book.execute("SELECT symbol, equity FROM accounts"):
            if abs(float(equity) - (start + sums.get(symbol, 0.0))) > BOOK_TOLERANCE:
                off += 1
        return off
    finally:
        book.close()
        ledger.close()


def _comparisons() -> object:
    path = ROOT / "audit" / "EXPERIMENTS_NEXT.yaml"
    if not path.exists():
        return None
    found = re.search(r"total_comparisons:\s*(\d+)", path.read_text(encoding="utf-8"))
    return int(found.group(1)) if found else None


FACTS: tuple[Fact, ...] = (
    Fact(
        "Replay-Trades im Journal",
        "mehrere Berichte nennen 2 734",
        lambda: _journal(
            "SELECT COUNT(*) FROM trades WHERE source!='live' AND closed_ts IS NOT NULL"
        ),
        2734, fixed=True,
    ),
    Fact(
        "geschlossene Live-Trades",
        "waechst; der Vorwaertslauf laeuft",
        lambda: _journal(
            "SELECT COUNT(*) FROM trades WHERE source='live' AND closed_ts IS NOT NULL"
        ),
        21, fixed=False,
    ),
    Fact(
        "Dateien im Live-Entscheidungspfad",
        "journal/version.py nennt 60; 56 am Morgen des 13.10., 58 am Mittag, "
        "59 seit live/book.py, 60 seit risk/schwellen.py am 19.10. "
        "DIE_VORWAERTSSTICHPROBE nennt weiter 59 -- die Stichprobe lief unter "
        "59, und ein Bericht ueber einen vergangenen Lauf wird nicht "
        "nachtraeglich auf den heutigen Stand gehoben.",
        _decision_closure, 60, fixed=True,
    ),
    Fact(
        "aktive Setups",
        "die Signatur nennt ['A','B','E','F','G']",
        lambda: sorted(_active_setups()), ["A", "B", "E", "F", "G"], fixed=True,
    ),
    Fact(
        "Setups IM Replay-Journal",
        "EVIDENZ_UND_RISIKO_AUDIT: enthaelt C, enthaelt kein E",
        lambda: sorted(_setups_in_journal("replay")), ["A", "B", "C", "F", "G"], fixed=True,
    ),
    Fact(
        "total_comparisons",
        "die Mächtigkeitsrechnungen korrigieren auf diese Zahl",
        _comparisons, 67, fixed=False,
    ),
    Fact(
        "verunreinigte Live-Signale",
        "AUDIT 3.3 sagte 0; seit 11.10. 16:00 UTC ist es 1 (XRPUSDT)",
        _contaminated_live_signals, 1, fixed=True,
    ),
    Fact(
        "Konten, deren Buch nicht stimmt",
        "BTCUSDT traegt einen Trade aus einer zerstoerten Generation; unter "
        "geteilter Kasse EIN Abgleich statt zwoelf, Luecke +55,0481",
        _books_that_disagree, 1, fixed=True,
    ),
)

COMMAND = re.compile(r"^\s*(python|pytest)\s+(\S+)", re.M)


def reproduction_commands() -> dict[Path, set[str]]:
    """Jedes Skript, das ein Bericht als Reproduktion nennt."""
    found: dict[Path, set[str]] = {}
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        scripts = {
            target for _, target in COMMAND.findall(text)
            if target.startswith(("scripts/", "tests/"))
        }
        if scripts:
            found[doc] = scripts
    return found


def check_facts() -> int:
    """Tier 2. Gibt die Zahl der Beanstandungen zurueck."""
    print("\n  Zahlen gegen die Daten:\n")
    print(f"    {'Behauptung':34s} {'erwartet':>16s} {'gemessen':>16s}  Urteil")
    print("    " + "-" * 76)
    wrong = 0
    for fact in FACTS:
        try:
            got = fact.measure()
        except Exception as problem:  # ein Fehler hier ist selbst der Befund
            print(f"    {fact.label:34s} {'?':>16s} {'FEHLER':>16s}  {problem}")
            wrong += 1
            continue
        if fact.fixed:
            good = got == fact.expected
            verdict = "stimmt" if good else "ABWEICHUNG"
        else:
            good = (
                isinstance(got, int)
                and isinstance(fact.expected, int)
                and got >= fact.expected
            )
            verdict = "stimmt (waechst)" if good else "ABWEICHUNG"
        if not good:
            wrong += 1
        print(f"    {fact.label:34s} {str(fact.expected)[:16]:>16s} "
              f"{str(got)[:16]:>16s}  {verdict}")
        if not good:
            print(f"      ^ {fact.where}")
    return wrong


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slow", action="store_true",
                        help="jedes genannte Skript zusaetzlich mit --help starten")
    args = parser.parse_args()

    print("=" * 74)
    print("Halten die Berichte, was sie behaupten?")
    print("=" * 74)

    # --- Tier 1 ------------------------------------------------------------ #
    commands = reproduction_commands()
    named = {s for scripts in commands.values() for s in scripts}
    missing: list[tuple[Path, str]] = []
    for doc, scripts in commands.items():
        for script in sorted(scripts):
            if not (ROOT / script).exists():
                missing.append((doc, script))

    print(f"\n  {len(DOCS)} Berichte, {len(commands)} mit Reproduktionsbefehl, "
          f"{len(named)} genannte Skripte")
    if missing:
        print(f"\n  FEHLENDE SKRIPTE ({len(missing)}):")
        for doc, script in missing:
            print(f"    {doc.name:44s} -> {script}")
    else:
        print("    Jedes genannte Skript existiert.")

    broken: list[str] = []
    if args.slow:
        print("\n  Startet jedes Skript mit --help:")
        for script in sorted(named):
            if script.startswith("tests/"):
                continue
            done = subprocess.run(
                [sys.executable, str(ROOT / script), "--help"],
                capture_output=True, text=True, cwd=ROOT, timeout=120, check=False,
            )
            mark = "ok" if done.returncode == 0 else f"EXIT {done.returncode}"
            if done.returncode != 0:
                broken.append(script)
            print(f"    {script:48s} {mark}")

    wrong = check_facts()

    print()
    problems = len(missing) + len(broken) + wrong
    if problems:
        print(f"  {problems} Beanstandungen. Ein Bericht, dessen Zahl nicht mehr stimmt,")
        print("  ist nicht halb richtig -- er ist falsch, bis jemand ihn korrigiert.\n")
        return 1
    print("  Nichts zu beanstanden.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
