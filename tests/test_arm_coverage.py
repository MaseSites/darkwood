"""Ein halb gerechneter Arm darf nicht in den Bericht.

**Der Anlass.** Am 16.10.2026 lief `compare_exits.py --only-report` waehrend
die Arme noch rechneten. Im Speicher lagen fuer "Einstand bei 1 R" drei von
zwoelf Maerkten -- ETH, SOL, XRP. Welche drei, entscheidet die Rechenzeit und
nicht der Arm; ein Bericht darueber waere eine Auswahl gewesen.

Die vorhandene Warnung prueft auf LEER (`if not results[label]`) und liess
genau diesen Fall durch: drei Maerkte sind nicht leer.

Dazu zwei Loecher, die beim Einbau des Schutzes selbst entstanden und die
dieser Test mit abdeckt: `report()` nimmt `order[0]` als Basis, also wuerde
eine herausgefallene Basis stillschweigend durch den naechsten vollstaendigen
Arm ersetzt -- dieselbe Beschriftung ueber einer anderen Rechnung.

Der Test faehrt das Skript als Prozess, weil der Schutz in `main()` sitzt und
sein Verhalten die Ausgabe ist.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_exits.py"

#: Genug Trades, dass der Blockbootstrap etwas sagen kann -- unter
#: `MIN_OBSERVATIONS` druckt der Bericht "(zu wenige Trades)" und der Test
#: wuerde die Zeile aus dem falschen Grund finden.
PER_MARKET = 40


def _trades(seed: float) -> list[dict[str, object]]:
    return [
        {
            "r": seed + 0.01 * i,
            "opened_ts": 1_600_000_000_000 + 3_600_000 * i,
            "reason": "stop",
            "stop_moved": False,
        }
        for i in range(PER_MARKET)
    ]


def _cache(path: Path, rows: list[tuple[str, str, float]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for rule, symbol, seed in rows:
            handle.write(json.dumps({
                "rule": rule,
                "symbol": symbol,
                "trades": _trades(seed),
            }) + "\n")


def _run(cache: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Das Skript als Prozess -- mit festgenagelter Kodierung auf BEIDEN Seiten.

    **Warum beides noetig ist und eine Seite allein es schlimmer macht.** Ohne
    Angabe entscheidet die Umgebung, was durch die Leitung geht. Gemessen auf
    dieser Maschine, dasselbe Kind, dasselbe Wort "Maerkte":

    =========================  =====================
    ohne `PYTHONIOENCODING`    ``b'M\\xe4rkte'``  (cp1252)
    mit `PYTHONIOENCODING=utf-8`  ``b'M\\xc3\\xa4rkte'``  (UTF-8)
    =========================  =====================

    Der Test vergleicht gegen ``"3/4 Märkte"``. Ohne die Variable las er
    zufaellig richtig; mit ihr bekam er ``"3/4 MÃ¤rkte"`` und fiel -- waehrend
    einer ganz anderen Aenderung, was eine Viertelstunde Suche kostete.

    Nur ``encoding="utf-8"`` im Elternteil waere die falsche Haelfte der
    Behebung: sie haette den zweiten Fall geheilt und den ERSTEN gebrochen.
    Darum wird das Kind gezwungen, UTF-8 zu schreiben, *und* der Elternteil
    liest UTF-8. Dann ist die Umgebung ohne Belang -- was der Punkt ist: ein
    Test, der von der Spracheinstellung der Maschine abhaengt, prueft die
    Maschine mit.
    """
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--only-report", "--cache", str(cache), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=str(ROOT),
    )


BASE = "ohne (original)"
BREAK = "Einstand bei 1 R"


def test_der_teilweise_gerechnete_arm_kommt_nicht_in_den_bericht(tmp_path: Path) -> None:
    """Drei von vier Maerkten: benannt, aber nicht gerechnet."""
    cache = tmp_path / "arme.jsonl"
    markets = ["AUSDT", "BUSDT", "CUSDT", "DUSDT"]
    rows = [(BASE, m, -0.5) for m in markets]
    rows += [(BREAK, m, -0.2) for m in markets[:3]]  # DUSDT fehlt
    _cache(cache, rows)

    done = _run(cache, "--at", "1")
    assert done.returncode == 0, done.stderr

    assert "3/4 Märkte" in done.stdout
    assert "NICHT im Bericht" in done.stdout
    assert "DUSDT" in done.stdout, "der fehlende Markt wird benannt"

    # Und er erscheint in keiner Ergebniszeile. Die Basis schon.
    ergebniszeilen = [
        line for line in done.stdout.splitlines() if " n=" in line and " R" in line
    ]
    assert any(BASE in line for line in ergebniszeilen)
    assert not any(BREAK in line for line in ergebniszeilen), done.stdout


def test_der_vollstaendige_arm_kommt_herein(tmp_path: Path) -> None:
    """Die Gegenprobe: vier von vier wird gerechnet.

    Ohne sie wuerde ein Schutz, der ALLES aussperrt, diesen Test bestehen.
    """
    cache = tmp_path / "arme.jsonl"
    markets = ["AUSDT", "BUSDT", "CUSDT", "DUSDT"]
    rows = [(BASE, m, -0.5) for m in markets] + [(BREAK, m, -0.2) for m in markets]
    _cache(cache, rows)

    done = _run(cache, "--at", "1")
    assert done.returncode == 0, done.stderr

    assert "NICHT im Bericht" not in done.stdout
    ergebniszeilen = [
        line for line in done.stdout.splitlines() if " n=" in line and " R" in line
    ]
    assert any(BREAK in line for line in ergebniszeilen), done.stdout
    assert any("Differenz" in line for line in done.stdout.splitlines())


def test_eine_unvollstaendige_basis_bricht_ab(tmp_path: Path) -> None:
    """Die Basis darf nicht stillschweigend wechseln.

    `report()` nimmt `order[0]`. Faellt die Basis heraus, wuerde ohne diesen
    Abbruch der naechste vollstaendige Arm ihre Rolle uebernehmen und jede
    Differenz waere gegen etwas anderes gerechnet, als die Beschriftung sagt.
    """
    cache = tmp_path / "arme.jsonl"
    markets = ["AUSDT", "BUSDT", "CUSDT"]
    rows = [(BASE, m, -0.5) for m in markets[:2]]  # CUSDT fehlt der BASIS
    rows += [(BREAK, m, -0.2) for m in markets]
    _cache(cache, rows)

    done = _run(cache, "--at", "1")
    assert done.returncode != 0, done.stdout
    assert "Basis" in done.stdout + done.stderr
    # Und keine Ergebniszeile, die so tut, als sei etwas gemessen worden.
    assert " R  [" not in done.stdout


def test_disjunkte_maerkte_brechen_ab(tmp_path: Path) -> None:
    """Zwei Arme, je ein anderer Markt -- kein gemeinsamer Boden.

    Dieser Fall landet im Basis-Abbruch und nicht in einer eigenen Pruefung
    auf "kein Arm vollstaendig": `rules` beginnt immer mit der Basis, deckt
    sie alles, ist mindestens sie vollstaendig. Eine zweite Pruefung waere
    ein Zweig, den kein Test erreichen kann, und steht darum nicht im Code.
    """
    cache = tmp_path / "arme.jsonl"
    _cache(cache, [
        (BASE, "AUSDT", -0.5),
        (BREAK, "BUSDT", -0.2),
    ])
    done = _run(cache, "--at", "1")
    assert done.returncode != 0, done.stdout
    assert "Basis" in done.stdout + done.stderr
