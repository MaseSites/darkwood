"""Das Trial-Ledger bauen -- und zählen, was sich wirklich belegen lässt.

    python scripts/build_trial_ledger.py

**Warum.** Der Forschungsauftrag verlangt in §4.1: *„Jede getestete Variante,
einschliesslich verworfener Varianten, in einem Trial-Ledger protokollieren"*
und *„den vollständigen Suchraum dokumentieren"*. Artefakt 9 der Liste ist
`audit/TRIAL_LEDGER.csv`. Es gab es nicht.

**Und das ist nicht nur eine fehlende Datei.** Die Vorabregistrierung sagt in
`meta.prior_search`: **124 registrierte Versuche, 87 verschiedene Arme**.
Dieselben Zahlen stehen im Zustandsbericht. Gesucht, wo sie herkommen: sie
stehen **nur dort**, als Behauptung. `scripts/ratchet.py` führt 14 Arme mit
Zahlen und 24 Familien als Einzeiler. Eine Aufzählung der 124 existiert nicht.

Das ist für die Mehrfachkorrektur nicht gleichgültig. `total_comparisons`
steht auf 52, und der Kommentar daneben sagt, die Zahl solle *„die bereits
gelesenen Zellen der Vorgänger-Suche"* enthalten, *„soweit dieselbe Frage
betroffen ist"*. Ohne Aufzählung ist nicht prüfbar, ob das zutrifft.

Dieses Skript zählt deshalb zusammen, **was belegbar ist**, und schreibt die
Lücke zur Behauptung ausdrücklich hin, statt sie zu schliessen.

**Es erfindet nichts.** Jede Zeile trägt ihre Quelle, und die Quellen sind
nach Belegstärke getrennt:

* **Stufe A -- nachrechenbar.** `data/study_*.json` speichert je Zelle die
  vollständige R-Reihe. Mittelwert und Intervall werden hier **neu gerechnet**,
  nicht abgeschrieben.
* **Stufe B -- berichtet.** `ratchet.TRIED` trägt Arme mit Zahlen, aber ohne
  die Reihe dahinter.
* **Stufe C -- benannt.** `scripts/study_*.py` gibt es 46; für 39 davon liegt
  kein gespeichertes Ergebnis auf der Platte. Die Frage steht im Docstring,
  die Zahlen stehen in den Berichten.

Was nur behauptet ist, erscheint als eigene Zeile mit
`quelle=behauptet_ohne_aufzaehlung`.
"""

from __future__ import annotations

import csv
import glob
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.reporting.intervals import block_bootstrap

OUT = ROOT / "audit" / "TRIAL_LEDGER.csv"

#: Dasselbe korrigierte Niveau, auf das alles andere korrigiert wird.
LEVEL = 1.0 - 0.05 / 52
REGISTRY = ROOT / "audit" / "EXPERIMENTS_NEXT.yaml"
RATCHET = ROOT / "scripts" / "ratchet.py"

FIELDS = (
    "id", "quelle", "familie", "stufe", "status", "n",
    "mittel", "unten", "oben", "null_ausgeschlossen",
    "vergleiche", "bericht", "notiz",
)


def load_ratchet() -> object:
    spec = importlib.util.spec_from_file_location("ratchet", RATCHET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ratchet"] = module
    spec.loader.exec_module(module)
    return module


def excludes_zero(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return ""
    return "ja" if (low > 0 or high < 0) else "nein"


def rows_from_ratchet(module: object) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for result in module.TRIED:  # type: ignore[attr-defined]
        out.append({
            "id": result.arm,
            "quelle": "B_berichtet:ratchet.TRIED",
            "familie": "",
            "stufe": result.stage.name.lower(),
            "status": "verworfen",
            "n": result.n,
            "mittel": result.mean_r,
            "unten": result.low,
            "oben": result.high,
            "null_ausgeschlossen": excludes_zero(result.low, result.high),
            "vergleiche": 1,
            "bericht": "scripts/ratchet.py",
            "notiz": result.note,
        })
    for name, state, note in module.FAMILIES:  # type: ignore[attr-defined]
        out.append({
            "id": name,
            "quelle": "B_berichtet:ratchet.FAMILIES",
            "familie": name,
            "stufe": "",
            "status": state,
            "n": "", "mittel": "", "unten": "", "oben": "",
            "null_ausgeschlossen": "",
            # Eine Familie ist eine Zusammenfassung, kein einzelner Vergleich.
            # Sie hier als 1 zu zaehlen waere genau die Untertreibung, die
            # dieses Ledger sichtbar machen soll.
            "vergleiche": "",
            "bericht": "scripts/ratchet.py",
            "notiz": note[:300],
        })
    return out


def rows_from_stored_studies() -> list[dict[str, object]]:
    """Stufe A: die Zellen, deren R-Reihe gespeichert ist -- neu gerechnet.

    Das ist der belastbarste Teil des Ledgers. `data/study_*.json` trägt je
    Zelle `"SYMBOL|Arm"` auf die Liste der R-Werte, und damit ist jede Zahl
    hier nachrechenbar statt abgeschrieben. 60 Zellen aus sieben Dateien.
    """
    out: list[dict[str, object]] = []
    for path in sorted(glob.glob(str(ROOT / "data" / "study_*.json"))):
        name = Path(path).stem.replace("study_", "")
        body = json.loads(Path(path).read_text(encoding="utf-8"))
        # `cells` ist ein dict, kein Paarliste. Meine erste Inspektion hat
        # `items()` gedruckt und ich habe das als Liste gelesen.
        for key, series in (body.get("cells") or {}).items():
            values = [float(v) for v in series]
            if not values:
                continue
            symbol, _, arm = key.partition("|")
            interval = block_bootstrap(values, level=LEVEL)
            out.append({
                "id": f"{name}:{arm}@{symbol}",
                "quelle": f"A_nachrechenbar:data/study_{name}.json",
                "familie": name,
                "stufe": "nachrechenbar",
                "status": "verworfen",
                "n": len(values),
                "mittel": round(float(np.mean(values)), 6),
                "unten": round(interval.low, 6) if interval else "",
                "oben": round(interval.high, 6) if interval else "",
                "null_ausgeschlossen": (
                    excludes_zero(interval.low, interval.high) if interval else ""
                ),
                "vergleiche": 1,
                "bericht": f"data/study_{name}.json",
                "notiz": f"{arm} auf {symbol}; R-Reihe gespeichert, hier neu gerechnet",
            })
    return out


def rows_from_study_scripts(with_results: set[str]) -> list[dict[str, object]]:
    """Stufe C: Studien ohne gespeichertes Ergebnis, mit ihrer Frage."""
    out: list[dict[str, object]] = []
    for path in sorted(glob.glob(str(ROOT / "scripts" / "study_*.py"))):
        name = Path(path).stem.replace("study_", "")
        if name in with_results:
            continue
        text = Path(path).read_text(encoding="utf-8")
        # Die erste Zeile des Modul-Docstrings ist die Frage der Studie.
        # Absichtlich ohne Escape-Sequenz im Muster: ein `\n` in einem
        # Regex, das durch ein Here-Dokument lief, ist in diesem Projekt
        # schon dreimal zu einem echten Zeilenumbruch geworden.
        opening = text.find('"""')
        question = ""
        if opening >= 0:
            body = text[opening + 3 :]
            question = body.splitlines()[0].strip()[:200] if body else ""
        out.append({
            "id": f"study_{name}",
            "quelle": "C_benannt:scripts/study_*.py",
            "familie": name,
            "stufe": "benannt",
            "status": "Zahlen nur im Bericht",
            "n": "", "mittel": "", "unten": "", "oben": "",
            "null_ausgeschlossen": "",
            "vergleiche": "",
            "bericht": f"scripts/study_{name}.py",
            "notiz": question,
        })
    return out


def rows_from_registry() -> list[dict[str, object]]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    out: list[dict[str, object]] = []
    for experiment in data["experiments"]:
        result = experiment.get("result") or {}
        for arm in experiment.get("arms", []):
            out.append({
                "id": arm["id"],
                "quelle": "D_registriert:EXPERIMENTS_NEXT.yaml",
                "familie": experiment["id"],
                "stufe": "vorab_registriert",
                "status": experiment.get("status", ""),
                "n": result.get("faelle") or result.get("tage") or result.get("orders") or "",
                "mittel": "", "unten": "", "oben": "",
                "null_ausgeschlossen": "",
                "vergleiche": "",
                "bericht": result.get("bericht", ""),
                "notiz": arm.get("name", "")[:300],
            })
        out.append({
            "id": experiment["id"],
            "quelle": "D_registriert:EXPERIMENTS_NEXT.yaml",
            "familie": experiment["id"],
            "stufe": "angemeldete_zellen",
            "status": experiment.get("status", ""),
            "n": "", "mittel": "", "unten": "", "oben": "",
            "null_ausgeschlossen": "",
            "vergleiche": experiment["comparisons"],
            "bericht": result.get("bericht", ""),
            "notiz": experiment["title"][:300],
        })
    return out, data


def main() -> int:
    module = load_ratchet()
    rows = rows_from_ratchet(module)
    stored = rows_from_stored_studies()
    rows += stored
    with_results = {str(r["familie"]) for r in stored}
    named = rows_from_study_scripts(with_results)
    rows += named
    registry_rows, data = rows_from_registry()
    rows += registry_rows

    claimed_attempts = int(data["meta"]["prior_search"]["register_attempts"])
    claimed_arms = int(data["meta"]["prior_search"]["distinct_arms"])
    declared = int(data["meta"]["total_comparisons"])

    itemised_arms = sum(1 for r in rows if str(r["quelle"]).startswith("B_berichtet:ratchet.TRIED"))
    recomputable = len(stored)
    named_only = len(named)
    enumerable = itemised_arms + recomputable
    registered_arms = sum(1 for r in rows if r["stufe"] == "vorab_registriert")
    declared_cells = sum(int(r["vergleiche"]) for r in rows if r["stufe"] == "angemeldete_zellen")

    rows.append({
        "id": "LUECKE_vorgaengersuche",
        "quelle": "behauptet_ohne_aufzaehlung",
        "familie": "", "stufe": "", "status": "offen",
        "n": "", "mittel": "", "unten": "", "oben": "",
        "null_ausgeschlossen": "",
        "vergleiche": max(0, claimed_attempts - enumerable),
        "bericht": "audit/EXPERIMENTS_NEXT.yaml:meta.prior_search",
        "notiz": (
            f"meta.prior_search behauptet {claimed_attempts} Versuche und "
            f"{claimed_arms} Arme. Aufzaehlbar mit Zahlen sind {enumerable} "
            f"({recomputable} nachrechenbar aus data/study_*.json, "
            f"{itemised_arms} berichtet in ratchet.TRIED), dazu "
            f"{named_only} benannte Studien ohne gespeichertes Ergebnis. "
            f"Rest ohne Beleg: {max(0, claimed_attempts - enumerable)}."
        ),
    })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})

    print("=" * 76)
    print("Trial-Ledger")
    print("=" * 76)
    print(f"\n  {len(rows):,} Zeilen nach {OUT.relative_to(ROOT)}\n")
    print(f"  A nachrechenbar (R-Reihe gespeichert) {recomputable:>5}")
    print(f"  B berichtet (ratchet.TRIED)           {itemised_arms:>5}")
    print(f"  C benannt (Studie ohne Ergebnisdatei) {named_only:>5}")
    print(f"  --> mit Zahlen aufzaehlbar            {enumerable:>5}")
    print(f"  Familien als Einzeiler                "
          f"{sum(1 for r in rows if 'ratchet.FAMILIES' in str(r['quelle'])):>5}")
    print(f"  Vorab registrierte Arme             {registered_arms:>5}")
    print(f"  Angemeldete Vergleichszellen        {declared_cells:>5}")
    print(f"  total_comparisons im Register       {declared:>5}")
    print()
    print(f"  meta.prior_search behauptet         {claimed_attempts:>5} Versuche, "
          f"{claimed_arms} Arme")
    print(f"  davon mit Zahlen aufzaehlbar        {enumerable:>5}")
    print(f"  dazu benannt ohne Zahlen            {named_only:>5}")
    print(f"  OHNE JEDEN BELEG                    "
          f"{max(0, claimed_attempts - enumerable - named_only):>5}")
    print(
        "\n  Das ist keine Buchhaltungsfrage. `total_comparisons` traegt die\n"
        "  Mehrfachkorrektur, und der Kommentar daneben sagt, die Zahl solle die\n"
        "  bereits gelesenen Zellen der Vorgaenger-Suche enthalten, 'soweit\n"
        "  dieselbe Frage betroffen ist'. Ohne Aufzaehlung ist nicht pruefbar,\n"
        "  ob das zutrifft."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
