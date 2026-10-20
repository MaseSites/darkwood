"""Das zweite Papierkonto: 1.000 CHF, 30 % Margin bei 7x Hebel, aufstockend.

**Was das ist.** Ein getrennter Papierhandel, ausdrücklich beauftragt: „300
Franken von den 1.000 und noch einen 7x Hebel... dann den zweiten Trade mit
350, den dritten mit 400". Das Aufstocken steckt darin, dass die Margin ein
*Anteil* ist — wächst das Konto, wächst die Margin mit.

**Was daran getrennt ist, und warum jedes Stück davon getrennt sein muss:**

* **Eigener Kontospeicher** (`plan_paper.sqlite`). Das bestehende Konto wird
  nicht angefasst.
* **Eigene Risikokonfiguration.** Gemessen über die 7.335 Replay-Trades
  riskiert diese Regel im Median 4,38 % des Kontos, im 99. Perzentil 30,62 %.
  Der produktive Deckel steht bei 3 % — den rührt dieses Skript nicht an, es
  bringt seinen eigenen mit.
* **Eigene Laufsignatur.** Eine Zeile aus diesem Konto darf nie mit einer aus
  dem anderen gemittelt werden; die Signatur trägt `plan30x7`, damit das
  mechanisch unmöglich ist.

**Was vorher gemessen wurde und beim Lesen der Zahlen dazugehört.** Dieselbe
Regel über die gespeicherten 7.335 Trades: Höchststand 9.695 CHF nach 410
Trades, Kontoboden nach 787. Über 300 Umordnungen endeten 0 % über dem Start.
Siehe `scripts/run_plan_account.py` und `audit/`.

Das ist kein Grund, es nicht zu tun — es ist Papierhandel, und der Auftrag ist
ausdrücklich. Es ist der Grund, warum dieses Konto **getrennt** läuft und warum
die Zahl, die es produziert, nur für sich selbst spricht.

    python scripts/plantrade.py --status
    python scripts/plantrade.py --cycles 5
    python scripts/plantrade.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import papertrade

from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.risk.plansize import forward_sizer

#: Der Auftrag, in Zahlen. 300 von 1.000 Franken, siebenfacher Hebel.
MARGIN_ANTEIL, HEBEL = 0.30, 7.0

#: Der Kontospeicher dieses Laufs. NICHT `paper.sqlite`.
STATE_NAME = "plan_paper.sqlite"


def _plan_yaml() -> dict:
    """Die Ueberschreibungen aus dem Terminal, wenn es welche gibt.

    `config_offen/plan.yaml` wird vom Darkwood Terminal geschrieben ("Apply")
    und traegt Marginanteil, Hebel und Risikodeckel. Fehlt die Datei, gelten
    die Konstanten oben -- und die Signatur bleibt byte-gleich zu vorher,
    weil der Zusatz aus denselben Zahlen gebildet wird.

    Die Zahlen gehen in den SIGNATURZUSATZ (`plan30x7`, `plan50x10`, ...), damit
    Trades vor und nach einer Aenderung trennbar bleiben. Eine Groessenregel,
    die sich aendert, ohne eine Spur zu hinterlassen, waere derselbe Fehler,
    der die Vorwaertsstichprobe am 09.10. dreimal hat schrumpfen lassen.
    """
    import yaml
    pfad = Path(__file__).resolve().parent.parent / "config_offen" / "plan.yaml"
    if not pfad.exists():
        return {}
    try:
        return yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 -- eine kaputte Datei darf den Haendler nicht stoppen
        return {}


_PLAN = _plan_yaml()
MARGIN_ANTEIL = float(_PLAN.get("margin_share", MARGIN_ANTEIL))
HEBEL = float(_PLAN.get("leverage", HEBEL))

#: Das Etikett in der Laufsignatur. Ohne es liessen sich die Zeilen dieses
#: Kontos mit denen des anderen mitteln, und genau das darf nicht passieren.
SIGNATUR_ZUSATZ = f"plan{int(round(MARGIN_ANTEIL * 100))}x{HEBEL:g}"

#: Der Risikodeckel DIESES Kontos.
#:
#: 35 % und nicht 3 %: die Vorwaertsregel riskiert im 99. Perzentil 30,62 % des
#: Kontos, und ein Deckel, der darunter laege, wuerde die Regel still
#: verstuemmeln statt sie zu pruefen. Er ist trotzdem da -- ein Trade, der mehr
#: als ein Drittel des Kontos riskiert, ist auch unter dieser Regel ein Fehler
#: und kein Plan.
PLAN_MAX_RISIKO = 0.35


def plan_config(config_dir: Path | None = None) -> AppConfig:
    """Die Konfiguration dieses Kontos.

    **Der echte Deckel sitzt im Sizer** (`forward_sizer(max_risk_share=...)`)
    und prueft das gerechnete Risiko gegen das Konto. Der erste Entwurf setzte
    hier `absolute_max_risk_pct` hoch -- das waere ein vorgetaeuschter Deckel
    gewesen: jener Wert begrenzt das RISIKOBUDGET, und der Vorwaerts-Sizer
    liest kein Budget.

    **`--config-dir`, und warum es ein eigenes Verzeichnis sein muss.** Am
    20.10.2026 wurde auf Anweisung des Nutzers entschieden, die beiden
    Wirtschaftlichkeitstore dieses Kontos zu oeffnen. Der naheliegende Weg --
    `config/risk.yaml` aendern -- waere falsch gewesen, und zwar aus zwei
    Gruenden, die beide nichts mit der Entscheidung selbst zu tun haben:

    * Die Datei gilt GLOBAL. Sie haette auch das bestehende Papierkonto auf
      127.0.0.1:8787 umgestellt, das niemand umstellen wollte.
    * Der E17-Replay laeuft gerade ueber 68 Maerkte und liest dieselbe Datei.
      Seine vier Straenge starten bei einem Absturz neu -- ein Neustart haette
      die neue Konfiguration gelesen und die Stichprobe auf zwei Codestaende
      verteilt. Genau das, was E17 ueberhaupt erst noetig gemacht hat.

    Darum ein zweites Verzeichnis. Die Laufsignatur traegt die geaenderten
    Werte, also bleiben die Trades davor und danach unterscheidbar.
    """
    return load_config(config_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=None)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--config-dir", type=Path, default=None,
        help="Eigenes Konfigurationsverzeichnis. Ohne Angabe gilt config/. "
             "Mit config_offen/ sind die beiden Wirtschaftlichkeitstore offen.",
    )
    args = parser.parse_args()

    config = plan_config(args.config_dir)
    print("=" * 70)
    print("PLANKONTO -- getrennt vom bestehenden Papierkonto")
    print("=" * 70)
    print(f"  Groessenregel   {MARGIN_ANTEIL:.0%} Margin x {HEBEL:g}x Hebel, aufstockend")
    print(f"  Kontospeicher   {config.engine.paths.data_dir / STATE_NAME}")
    print(f"  Signaturzusatz  {SIGNATUR_ZUSATZ}")
    print(f"  Risikodeckel    {PLAN_MAX_RISIKO:.0%} je Trade, IM SIZER geprueft")
    # Die beiden Wirtschaftlichkeitstore in Klartext. Sie stehen hier, weil
    # sie seit dem 20.10. nicht mehr selbstverstaendlich sind: wer das Log
    # liest, soll ohne Nachsehen wissen, welches Konto er vor sich hat.
    _tore_offen = (config.risk.limits.max_cost_fraction_of_risk >= 1.0
                   or config.risk.limits.min_reward_risk <= 0.1)
    print(f"  Kostentor       {config.risk.limits.max_cost_fraction_of_risk:.2f}"
          f"   CRV-Tor {config.risk.limits.min_reward_risk:.2f}"
          f"   {'<<< OFFEN' if _tore_offen else '(produktiv)'}")
    if _tore_offen:
        print("                  Gemessen auf 3.553 abgelehnten Signalen:")
        print("                  -0.1464 R je Trade. Auf ausdrueckliche Anweisung.")
    print(f"                  (produktiv sind es "
          f"{config.risk.sizing.absolute_max_risk_pct:.0%} auf dem Budgetpfad,")
    print("                   den diese Regel nicht benutzt -- unberuehrt)")
    print()
    print("  GEMESSEN, bevor dieses Konto lief (scripts/run_plan_account.py,")
    print("  dieselbe Regel ueber die 7.335 gespeicherten Trades):")
    print("    Hoechststand 9.695 CHF nach 410 Trades, Kontoboden nach 787.")
    print("    Ueber 300 Umordnungen endeten 0 % ueber dem Start.")
    print()

    sizer = forward_sizer(
        margin_share=MARGIN_ANTEIL, leverage=HEBEL,
        # Der Deckel kommt aus plan.yaml, wenn das Terminal einen gesetzt hat;
        # sonst die Konstante. Er steht NICHT in der Signatur -- er aendert
        # nur, welche Trades verworfen werden, nicht ihre Groesse -- und das
        # ist eine bekannte Luecke, die hier benannt und nicht verschwiegen ist.
        max_risk_share=float(_PLAN.get("max_risk_share", PLAN_MAX_RISIKO)),
    )
    traders, source = papertrade.build_traders(
        [s.strip() for s in config.engine.symbols.active],
        offline=args.offline,
        config=config,
        state_name=STATE_NAME,
        signature_suffix=SIGNATUR_ZUSATZ,
        sizer=sizer,
    )
    if args.status:
        return papertrade.show_status(traders)
    return papertrade.run(traders, source, cycles=args.cycles)


if __name__ == "__main__":
    raise SystemExit(main())
