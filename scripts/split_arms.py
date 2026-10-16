"""Die angemeldeten Arme auf mehrere Kerne verteilen, statt 3,5 Tage zu warten.

    python scripts/split_arms.py --ways 6 --drop F --at 1.0 0.5 --target-cap 1.0 1.5 2.0

**Der Anlass ist eine Messung, keine Ungeduld.** `scripts/compare_exits.py`
rechnet seine Arme nacheinander: 12 Maerkte mal 7 Regeln = 84 volle Motorläufe,
gemessen rund 30 Minuten je Lauf, also 42 Kernstunden. Auf *einem* Kern sind
das 3,5 Tage — während diese Maschine 22 logische Kerne hat und vier davon
benutzt. Der Lauf war nicht langsam, er war seriell.

**Was dieses Skript tut und was ausdrücklich nicht.** Es teilt die MÄRKTE auf
N Prozesse auf, gibt jedem seinen eigenen Zwischenspeicher und startet sie.
Es rührt an keiner Regel, keiner Schwelle und keiner Auswertung: jeder Prozess
ruft dasselbe `compare_exits.py` mit denselben Armen auf, nur für weniger
Märkte. Am Ende werden die Zwischenspeicher zusammengelegt und
`--only-report` rechnet über alles.

Das ist erlaubt, weil die Märkte unabhängig sind — jeder Motorlauf liest seine
eigenen Kerzen und schreibt seine eigene Zeile. Es wäre NICHT erlaubt, die
Regeln aufzuteilen: die Differenz zur Basis wird über dieselbe Marktmenge
gebildet, und zwei Arme über verschiedene Märkte zu vergleichen wäre ein
anderer Versuch.

**Die Basis wird geerbt, wo sie bewiesen gleich ist.** `data/replay_fills/`
hält bereits einen Basislauf je Markt. Über die acht Märkte, die der serielle
Lauf schon neu gerechnet hatte, wurden beide Mengen Trade für Trade
verglichen — 4.650 Trades, R auf 1e-12, Zeitstempel und Ausgangsgrund
identisch. Für diese acht wird die Datei als Basis übernommen statt noch
einmal gerechnet. Die übrigen vier rechnen frisch: eine Gleichheit, die man
nicht geprüft hat, ist eine Annahme, und vier Motorläufe sind billiger als
eine Annahme in einer Basis, gegen die sechs Arme gemessen werden.

Nur lesen, ausser den Zwischenspeichern in `data/`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

#: Was ein Motorprozess an Arbeitsspeicher belegt, gemessen am 15.10.2026 ueber
#: sechs gleichzeitige Laeufe: 1.210 MB im Mittel. Aufgerundet, weil die
#: Maerkte mit laengerer Historie darueber liegen.
MB_PER_PROCESS = 1_400

#: Was fuer das Betriebssystem, den Haendler, das Dashboard und den Backfill
#: frei bleiben muss. Unterschreitet man das, faengt Windows an auszulagern,
#: und dann ist JEDER Prozess langsam -- nicht nur der letzte.
MB_RESERVE = 4_000


def capacity() -> tuple[int, str]:
    """Wie viele Motorprozesse diese Maschine traegt, und warum.

    **Der Anlass ist ein Fehler, der sechs Stunden gekostet hat.** Am
    15.10.2026 liefen neun Motorprozesse gleichzeitig auf 16 physischen
    Kernen mit 32 GB. Jeder braucht rund 1,2 GB, und das System fing an
    auszulagern: 20 GB Auslagerung, 120.000 Seitenfehler je Sekunde. Ab da
    wurde kein einzelner Lauf mehr fertig -- die letzte fertige Zeile
    stammte von 02:21, sechs Stunden spaeter war immer noch keine neue da,
    waehrend ein Lauf vorher 40 Minuten brauchte.

    Das ist nicht "etwas langsamer", sondern ein Umschlagpunkt: solange
    alles in den Speicher passt, kostet ein weiterer Prozess nichts; sobald
    es nicht mehr passt, kostet er ALLE.

    Gerechnet wird der kleinere von zwei Werten -- was der Speicher traegt
    und was die physischen Kerne tragen. Logische Kerne zaehlen hier nicht:
    der Motor ist eine Schleife ueber Minutenbalken, und zwei
    Hyperthreads auf einem Kern teilen sich dieselben Rechenwerke.
    """
    free_mb = _free_memory_mb()
    by_memory = max(1, (free_mb - MB_RESERVE) // MB_PER_PROCESS)
    by_cores = max(1, _physical_cores() - 2)
    if by_memory <= by_cores:
        return int(by_memory), (
            f"Speicher: {free_mb:,} MB frei, {MB_RESERVE:,} MB Reserve, "
            f"{MB_PER_PROCESS:,} MB je Prozess"
        )
    return int(by_cores), f"Kerne: {_physical_cores()} physisch, zwei bleiben frei"


def _free_memory_mb() -> int:
    """Freier Arbeitsspeicher in MB, oder eine vorsichtige Annahme."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1KB)"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return int(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        # Vorsichtig nach unten: lieber zu wenige Prozesse als Auslagern.
        return MB_RESERVE + MB_PER_PROCESS * 2


def _physical_cores() -> int:
    """Physische Kerne, nicht logische. Hyperthreads teilen die Rechenwerke."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor | "
             "Measure-Object -Property NumberOfCores -Sum).Sum"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return max(1, int(out.stdout.strip()))
    except (OSError, ValueError, subprocess.SubprocessError):
        return max(1, (os.cpu_count() or 2) // 2)

#: Die Maerkte, deren Basislauf Trade fuer Trade gegen `data/replay_fills/`
#: geprueft wurde. Nur fuer diese wird die Datei uebernommen.
VERIFIED = (
    "ADAUSDT", "AVAXUSDT", "BTCUSDT", "DOGEUSDT",
    "ETHUSDT", "LINKUSDT", "SOLUSDT", "XRPUSDT",
)

BASELINE = "ohne (original)"


def already_cached(cache: Path) -> set[tuple[str, str]]:
    """Welche (Regel, Markt)-Paare schon drinstehen.

    Gebraucht, damit `seed` nichts doppelt schreibt, OHNE die Datei zu
    loeschen. Die erste Fassung loeschte sie statt zu lesen, und das hat
    fuenf fertige Motorlaeufe gekostet -- siehe `seed`.
    """
    if not cache.is_file():
        return set()
    done: set[tuple[str, str]] = set()
    for line in cache.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # Eine halbe Zeile vom harten Beenden. Sie wird ignoriert und
            # nicht entfernt: `compare_exits.load_cache` ueberliest sie
            # ebenso, und eine Datei zu reparieren, die noch jemand
            # schreibt, ist der schlechtere Umgang damit.
            continue
        done.add((row.get("rule", ""), row.get("symbol", "")))
    return done


def inherit(cache: Path, symbols: list[str], prefix: str) -> int:
    """Fertige Laeufe aus den GESCHWISTERDATEIEN uebernehmen.

    **Warum das noetig ist, seit die Kapazitaet gerechnet wird.** Die Maerkte
    werden reihum auf N Prozesse verteilt, und N haengt jetzt am freien
    Speicher -- heute 4, gestern 6, davor 7. Mit anderem N wandert ein Markt
    in einen anderen Eimer, liest eine Datei, in der seine Ergebnisse nicht
    stehen, und rechnet sie neu. Bei 76 Laeufen zu je 40 Minuten ist das die
    gesamte Arbeit.

    Geschrieben wird weiter in die eigene Datei -- vier Prozesse, die
    gleichzeitig in eine Datei anhaengen, koennten ihre Zeilen ineinander
    schieben, und eine halbe JSON-Zeile ist ein verlorener Lauf. Gelesen wird
    aus allen.
    """
    mine = already_cached(cache)
    wanted = set(symbols)
    taken = 0
    with cache.open("a", encoding="utf-8") as handle:
        for sibling in sorted(cache.parent.glob(f"{prefix}_*.jsonl")):
            if sibling == cache:
                continue
            for line in sibling.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (row.get("rule", ""), row.get("symbol", ""))
                if key[1] not in wanted or key in mine:
                    continue
                handle.write(line + "\n")
                mine.add(key)
                taken += 1
    return taken


def seed(cache: Path, symbols: list[str], fills_dir: Path) -> int:
    """Den Basislauf aus den Replay-Dateien in den Zwischenspeicher legen.

    **Haengt an, loescht nie.** Die erste Fassung rief
    `cache.unlink(missing_ok=True)` davor, und zwar auch bei `--dry-run`.
    Zwei Folgen: ein Schalter, der "nichts starten" verspricht, vernichtete
    Zustand -- und, schlimmer, ein normaler NEUSTART tat dasselbe. Der
    Zwischenspeicher existiert, damit ein Lauf fortsetzbar ist; ihn beim
    Start zu loeschen macht genau das unmoeglich. Gekostet hat es fuenf
    fertige Motorlaeufe, rund 3,3 Stunden.

    Nur fuer geprueft gleiche Maerkte (`VERIFIED`). `stop_moved` ist in der
    Basis immer falsch -- die Einstand-Regel ist dort aus, der Stop wird
    nie bewegt -- und das Feld existierte in den alten Dateien noch nicht.
    """
    done = already_cached(cache)
    written = 0
    with cache.open("a", encoding="utf-8") as handle:
        for symbol in symbols:
            if symbol not in VERIFIED or (BASELINE, symbol) in done:
                continue
            path = fills_dir / f"{symbol}.json"
            if not path.exists():
                continue
            fills = json.loads(path.read_text(encoding="utf-8")).get("fills", [])
            trades = [
                {
                    "r": fill["r_multiple"],
                    "opened_ts": fill["opened_ts"],
                    "reason": fill["reason"],
                    "stop_moved": False,
                }
                for fill in fills
            ]
            handle.write(json.dumps({
                "rule": BASELINE, "symbol": symbol, "trades": trades,
            }) + "\n")
            written += 1
    return written


def launch(
    index: int,
    bucket: list[str],
    *,
    args: argparse.Namespace,
    data: Path,
    rules: int,
) -> subprocess.Popen | None:
    """Einen Eimer vorbereiten und starten. `None` bei `--dry-run`.

    Herausgeloest, weil `main()` sonst drei Dinge tut -- Argumente lesen,
    Kapazitaet bestimmen, und je Eimer erben, saeen, Befehl bauen, starten --
    und das dritte ist das, was waechst.

    Die Reihenfolge ist Absicht: erst von den Geschwistern erben, dann die
    Basis aus den Replay-Dateien fuer das, was dann noch fehlt. Umgekehrt
    schriebe man eine Basiszeile, die nebenan schon als vollstaendiger Lauf
    liegt.
    """
    cache = data / f"{args.prefix}_{index}.jsonl"
    # NICHT loeschen. Siehe `seed`: genau das hat fuenf fertige Motorlaeufe
    # gekostet, und bei `--dry-run` sogar ohne Gegenwert.
    if args.dry_run:
        taken = seeded = 0
    else:
        taken = inherit(cache, bucket, args.prefix)
        seeded = seed(cache, bucket, data / "replay_fills")
    have = len(already_cached(cache))

    command = [str(PYTHON), "-u", str(ROOT / "scripts" / "compare_exits.py"),
               "--cache", str(cache)]
    for key in args.drop:
        command += ["--drop", key]
    command += ["--at", *[f"{v:g}" for v in args.at]]
    command += ["--target-cap", *[f"{v:g}" for v in args.target_cap]]
    for symbol in bucket:
        command += ["--symbol", symbol]

    todo = max(0, rules * len(bucket) - have)
    teile = []
    if taken:
        teile.append(f"{taken} von Geschwistern")
    if seeded:
        teile.append(f"{seeded} Basis aus Dateien")
    note = ", ".join(teile) if teile else f"{have} schon da"
    print(f"  [{index}] {', '.join(bucket):28s} {todo:3d} Laeufe ({note})")

    if args.dry_run:
        return None
    log = (data / f"{args.prefix}_{index}.log").open("w", encoding="utf-8")
    return subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ways", type=int, default=0,
        help="Wie viele Prozesse; 0 rechnet es aus dem freien Speicher",
    )
    parser.add_argument(
        "--force-ways", action="store_true",
        help="--ways auch oberhalb der Kapazitaet nehmen",
    )
    parser.add_argument("--drop", action="append", default=[])
    parser.add_argument("--at", type=float, nargs="*", default=[])
    parser.add_argument("--target-cap", type=float, nargs="*", default=[])
    parser.add_argument("--prefix", default="arms", help="Name der Zwischenspeicher")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config()
    data = config.engine.paths.data_dir
    symbols = list(config.engine.symbols.active)

    # Die Kapazitaet entscheidet, nicht der Wunsch.
    fits, why = capacity()
    wanted = args.ways or fits
    if wanted > fits and not args.force_ways:
        print(
            f"{wanted} Prozesse angefragt, die Maschine traegt {fits}.\n"
            f"  {why}\n"
            "  Gekappt. Der Grund steht in `capacity()`: ueber dieser Zahl faengt\n"
            "  Windows an auszulagern, und dann wird KEIN Lauf mehr fertig --\n"
            "  am 15.10.2026 sechs Stunden lang keiner. Mit --force-ways\n"
            "  trotzdem."
        )
        wanted = fits
    elif wanted > fits:
        print(f"WARNUNG: {wanted} Prozesse ueber der Kapazitaet von {fits} ({why}).")
    ways = max(1, min(wanted, len(symbols)))
    print(f"Kapazitaet: {fits} Prozesse ({why})")

    # Reihum verteilt, nicht in Bloecken: die Maerkte unterscheiden sich stark
    # in der Historienlaenge, und ein Block aus drei langen waere der Prozess,
    # auf den alle anderen warten.
    buckets: list[list[str]] = [[] for _ in range(ways)]
    for index, symbol in enumerate(symbols):
        buckets[index % ways].append(symbol)

    rules = 1 + len(args.drop) + len(args.at) + len(args.target_cap)
    print(f"{len(symbols)} Maerkte, {rules} Regeln, {ways} Prozesse")

    started = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        process = launch(index, bucket, args=args, data=data, rules=rules)
        if process is not None:
            started.append(process)

    if args.dry_run:
        print("\n--dry-run: nichts gestartet")
        return 0
    print(f"\n{len(started)} Prozesse gestartet. Zusammenlegen mit:")
    print(f"  cat {data}/{args.prefix}_*.jsonl > {data}/{args.prefix}_alle.jsonl")
    print(f"  python scripts/compare_exits.py --only-report "
          f"--cache {data}/{args.prefix}_alle.jsonl \\")
    print(f"      --drop {' --drop '.join(args.drop) if args.drop else ''} "
          f"--at {' '.join(f'{v:g}' for v in args.at)} "
          f"--target-cap {' '.join(f'{v:g}' for v in args.target_cap)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
