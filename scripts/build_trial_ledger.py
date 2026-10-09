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

**Es erfindet nichts.** Jede Zeile trägt ihre Quelle. Was nur behauptet ist,
erscheint als eigene Zeile mit `quelle=behauptet_ohne_aufzaehlung`.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "audit" / "TRIAL_LEDGER.csv"
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
            "quelle": "ratchet.TRIED",
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
            "quelle": "ratchet.FAMILIES",
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


def rows_from_registry() -> list[dict[str, object]]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    out: list[dict[str, object]] = []
    for experiment in data["experiments"]:
        result = experiment.get("result") or {}
        for arm in experiment.get("arms", []):
            out.append({
                "id": arm["id"],
                "quelle": "EXPERIMENTS_NEXT.yaml",
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
            "quelle": "EXPERIMENTS_NEXT.yaml",
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
    registry_rows, data = rows_from_registry()
    rows += registry_rows

    claimed_attempts = int(data["meta"]["prior_search"]["register_attempts"])
    claimed_arms = int(data["meta"]["prior_search"]["distinct_arms"])
    declared = int(data["meta"]["total_comparisons"])

    itemised_arms = sum(1 for r in rows if r["quelle"] == "ratchet.TRIED")
    registered_arms = sum(1 for r in rows if r["stufe"] == "vorab_registriert")
    declared_cells = sum(int(r["vergleiche"]) for r in rows if r["stufe"] == "angemeldete_zellen")

    rows.append({
        "id": "LUECKE_vorgaengersuche",
        "quelle": "behauptet_ohne_aufzaehlung",
        "familie": "", "stufe": "", "status": "offen",
        "n": "", "mittel": "", "unten": "", "oben": "",
        "null_ausgeschlossen": "",
        "vergleiche": claimed_attempts - itemised_arms,
        "bericht": "audit/EXPERIMENTS_NEXT.yaml:meta.prior_search",
        "notiz": (
            f"meta.prior_search behauptet {claimed_attempts} Versuche und "
            f"{claimed_arms} Arme. Aufzaehlbar sind {itemised_arms} Arme mit "
            f"Zahlen aus ratchet.TRIED. Fuer die Differenz existiert keine "
            f"Liste -- weder hier noch im Zustandsbericht."
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
    print(f"  Arme mit Zahlen, aufzaehlbar        {itemised_arms:>5}")
    print(f"  Familien als Einzeiler              "
          f"{sum(1 for r in rows if r['quelle'] == 'ratchet.FAMILIES'):>5}")
    print(f"  Vorab registrierte Arme             {registered_arms:>5}")
    print(f"  Angemeldete Vergleichszellen        {declared_cells:>5}")
    print(f"  total_comparisons im Register       {declared:>5}")
    print()
    print(f"  meta.prior_search behauptet         {claimed_attempts:>5} Versuche, "
          f"{claimed_arms} Arme")
    print(f"  davon aufzaehlbar                   {itemised_arms:>5}")
    print(f"  NICHT aufzaehlbar                   {claimed_attempts - itemised_arms:>5}")
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
