"""Wo endet das letzte Trainingslabel -- und wo beginnt die erste Vorhersage?

    freqtrade/.venv/Scripts/python scripts/ft_label_boundary.py
    freqtrade/.venv/Scripts/python scripts/ft_label_boundary.py --horizon 12

Läuft unter dem **Freqtrade**-venv, nicht unter dem Projekt-venv -- Freqtrade
ist dort installiert und nicht hier.

Der Zustandsbericht behauptete pauschal: *"FreqAI hat kein Purging und kein
Embargo. Labels nutzen `shift(-label_period_candles)`, also überlappt jede
Foldgrenze um so viele Kerzen -- aus der Konfiguration nicht abschaltbar."*

Der Forschungsauftrag verlangt, diese Aussage gegen die **installierte** Version
zu prüfen, nicht gegen die Online-Dokumentation, und dafür einen winzigen
künstlichen Datensatz mit bekanntem Trainingsende, bekannter Entscheidung und
bekannter Label-Endzeit zu bauen. Genau das tut dieses Skript: jede Zeile ist
von Hand nachzählbar, und die Grenzen werden nicht beschrieben, sondern gedruckt.

**Es gibt zwei verschiedene Grenzen, und die pauschale Aussage wirft sie
zusammen.**

1. **Training -> Vorhersage.** Hier schützt der Shift sich selbst: eine Zeile,
   deren Label über das Trainingsende hinausreicht, ist NaN, und
   `filter_features` wirft NaN-Labels aus dem Training. Das steht so im
   installierten Code (`data_kitchen.py`, `drop_index_labels`).
2. **Training -> interne Validierung.** Hier schützt nichts.
   `make_train_test_datasets` ruft `sklearn.train_test_split` mit
   `shuffle=False` auf -- chronologisch korrekt geordnet, aber **ohne Abstand**.
   Das letzte Trainingslabel reicht `horizon` Kerzen in die Validierung hinein.

Und das ist die Grenze, an der Early Stopping und die berichteten
Test-Kennzahlen leben. `shuffle=False` ordnet die Zeilen, es entfernt keine
überlappenden Labels.

**Was `buffer_train_data_candles` leistet.** Der installierte Code schneidet in
`buffer_timerange` **beide** Enden des Trainings-Zeitfensters um `buffer`
Kerzen. Das ist für `argrelextrema`-Randeffekte gedacht, wie sein Docstring
sagt. Es ist kein Panel-Purging: es schützt einen festen Rand des
Trainingsfensters und nicht die interne Teilung.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

#: Wohin FreqAI seine Modellpfade legen will. Ein Wegwerfverzeichnis, weil
#: dieses Skript nichts trainiert und nichts speichern soll.
SCRATCH = Path(tempfile.gettempdir()) / "traidingbrain_ft_boundary"

try:
    from freqtrade.freqai.data_kitchen import FreqaiDataKitchen
except ImportError:  # pragma: no cover
    raise SystemExit(
        "Freqtrade ist im aktiven Interpreter nicht importierbar.\n"
        "Dieses Skript laeuft unter dem Freqtrade-venv:\n"
        "  freqtrade/.venv/Scripts/python scripts/ft_label_boundary.py"
    ) from None

#: Kerzen im Spielzeug-Datensatz. Klein genug, dass jede Zeile von Hand
#: nachzaehlbar ist, und gross genug fuer eine Teilung mit test_size.
ROWS = 40

#: Label-Horizont in Kerzen -- das `label_period_candles` dieses Tests.
DEFAULT_HORIZON = 6

#: Anteil, den FreqAI per Voreinstellung als interne Validierung abspaltet.
TEST_SIZE = 0.25

#: Zeitrahmen des Spielzeugs. Eine Stunde, damit die Zeitstempel lesbar sind.
TIMEFRAME = "1h"
STEP = pd.Timedelta(TIMEFRAME)


def toy_config(*, buffer: int, test_size: float) -> dict:
    """Die kleinste Konfiguration, die `FreqaiDataKitchen` annimmt."""
    return {
        "timeframe": TIMEFRAME,
        # Der Konstruktor liest beides, bevor irgendetwas gerechnet wird:
        # `set_all_pairs` ruft `.get` auf der Whitelist, und
        # `get_full_models_path` baut einen Pfad unter `user_data_dir`. Ohne
        # diese zwei Schluessel schlaegt schon das Anlegen fehl.
        "exchange": {"pair_whitelist": ["TOY/USDT"]},
        "user_data_dir": SCRATCH,
        "freqai": {
            "feature_parameters": {
                "buffer_train_data_candles": buffer,
                "shuffle_after_split": False,
                "weight_factor": 0,
            },
            "data_split_parameters": {"test_size": test_size, "shuffle": False},
        },
    }


def toy_frame(*, horizon: int) -> pd.DataFrame:
    """Kerzen mit einem Merkmal und einem um `horizon` verschobenen Label.

    Der Preis steigt um genau eins je Kerze, damit jede Rendite von Hand
    nachrechenbar ist und ein falsch ausgerichtetes Label sofort auffaellt.
    """
    dates = pd.date_range("2026-01-01", periods=ROWS, freq=TIMEFRAME, tz="UTC")
    close = pd.Series(np.arange(ROWS, dtype=float) + 100.0)
    frame = pd.DataFrame({"date": dates, "close": close})
    frame["%-feature"] = close.diff().fillna(0.0)
    # Genau die Konstruktion, die der Zustandsbericht als leckend bezeichnet.
    frame["&-target"] = close.shift(-horizon) / close - 1.0
    # Die Zeit, zu der das Label dieser Zeile FESTSTEHT. Das ist die Groesse,
    # die ueber Leakage entscheidet -- nicht der Zeitstempel der Zeile.
    frame["label_end"] = frame["date"].shift(-horizon)
    return frame


def report_training_boundary(frame: pd.DataFrame, *, horizon: int, buffer: int) -> bool:
    """Reicht ein Trainingslabel ueber das Trainingsende hinaus?"""
    kitchen = FreqaiDataKitchen(
        toy_config(buffer=buffer, test_size=TEST_SIZE), live=True, pair="TOY/USDT"
    )
    features, labels = kitchen.filter_features(
        frame, ["%-feature"], label_list=["&-target"], training_filter=True
    )

    used = kitchen.train_dates
    last_used = used.iloc[-1]
    last_label_end = last_used + horizon * STEP
    window_end = frame["date"].iloc[-1]
    first_prediction = window_end + STEP

    print("\n--- Grenze 1: Training -> Vorhersage ---")
    print(f"  Kerzen im Fenster                 {len(frame)}")
    print(f"  nach filter_features uebrig       {len(features)}")
    print(f"  verworfen                         {len(frame) - len(features)} (erwartet {horizon})")
    print(f"  letzte benutzte Trainingszeile    {last_used}")
    print(f"  deren Label steht fest am         {last_label_end}")
    print(f"  Fensterende                       {window_end}")
    print(f"  erste Vorhersage waere            {first_prediction}")

    clean = last_label_end < first_prediction
    print(f"\n  label_end < erste Vorhersage:     {'JA' if clean else 'NEIN -- LECK'}")
    print(
        "  Grund: eine Zeile, deren Label ueber das Fensterende hinausreicht, ist\n"
        "  NaN, und `filter_features` wirft NaN-Labels aus dem Training\n"
        "  (data_kitchen.py, `drop_index_labels`). Der Shift schuetzt sich hier\n"
        "  also selbst -- ohne dass ein Parameter gesetzt werden muesste."
    )
    assert len(labels) == len(features), "Labels und Merkmale unterschiedlich lang"
    return clean


def report_internal_split(frame: pd.DataFrame, *, horizon: int, buffer: int) -> bool:
    """Reicht ein Trainingslabel in die interne Validierung hinein?"""
    kitchen = FreqaiDataKitchen(
        toy_config(buffer=buffer, test_size=TEST_SIZE), live=True, pair="TOY/USDT"
    )
    features, labels = kitchen.filter_features(
        frame, ["%-feature"], label_list=["&-target"], training_filter=True
    )
    dates = kitchen.train_dates.reset_index(drop=True)
    split = kitchen.make_train_test_datasets(features, labels)

    n_train = len(split["train_features"])
    n_test = len(split["test_features"])
    last_train_date = dates.iloc[n_train - 1]
    first_test_date = dates.iloc[n_train]
    last_train_label_end = last_train_date + horizon * STEP

    print("\n--- Grenze 2: Training -> interne Validierung ---")
    print(f"  test_size                         {TEST_SIZE}")
    print(f"  Trainingszeilen                   {n_train}")
    print(f"  Validierungszeilen                {n_test}")
    print(f"  letzte Trainingszeile             {last_train_date}")
    print(f"  deren Label steht fest am         {last_train_label_end}")
    print(f"  erste Validierungszeile           {first_test_date}")

    overlap = last_train_label_end > first_test_date
    print(f"\n  label_end > erste Validierung:    {'JA -- LECK' if overlap else 'NEIN'}")
    if overlap:
        reach = int((last_train_label_end - first_test_date) / STEP) + 1
        print(
            f"  Das letzte Trainingslabel reicht {reach} Kerzen in die Validierung.\n"
            f"  `make_train_test_datasets` ruft `sklearn.train_test_split` mit\n"
            f"  `shuffle=False` -- chronologisch geordnet, aber OHNE Abstand.\n"
            f"  Ordnung ist nicht Purging. An dieser Grenze leben Early Stopping\n"
            f"  und die berichteten Test-Kennzahlen."
        )
    return not overlap


def report_buffer(frame: pd.DataFrame, *, horizon: int) -> None:
    """Was `buffer_train_data_candles` tatsaechlich bewirkt."""
    print("\n--- Was der dokumentierte Puffer leistet ---")
    print(f"  {'buffer':>7s}  {'Trainingszeilen':>16s}  {'interne Grenze':>15s}")
    for buffer in (0, horizon, 2 * horizon):
        kitchen = FreqaiDataKitchen(
            toy_config(buffer=buffer, test_size=TEST_SIZE), live=True, pair="TOY/USDT"
        )
        features, labels = kitchen.filter_features(
            frame, ["%-feature"], label_list=["&-target"], training_filter=True
        )
        dates = kitchen.train_dates.reset_index(drop=True)
        split = kitchen.make_train_test_datasets(features, labels)
        n_train = len(split["train_features"])
        gap_ok = dates.iloc[n_train - 1] + horizon * STEP <= dates.iloc[n_train]
        print(f"  {buffer:>7d}  {len(features):>16d}  {'sauber' if gap_ok else 'LECK':>15s}")
    print(
        "\n  Der Puffer aendert hier nichts an der internen Grenze, und das ist kein\n"
        "  Fehler: `buffer_timerange` schneidet die Enden des TRAININGS-ZEITFENSTERS,\n"
        "  bevor die Zeilen gefiltert werden. Dieses Skript uebergibt den Rahmen\n"
        "  direkt, also greift er nicht -- genau das ist die Aussage. Ein Parameter,\n"
        "  der einen festen Fensterrand schuetzt, ist kein Ersatz fuer einen Abstand\n"
        "  an der Teilung."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    args = parser.parse_args()

    frame = toy_frame(horizon=args.horizon)
    print("=" * 78)
    print(f"FreqAI-Label-Grenzen, installierte Version, Horizont {args.horizon} Kerzen")
    print("=" * 78)
    print(f"\nSpielzeug: {ROWS} Kerzen {TIMEFRAME}, Preis +1 je Kerze, Label = shift(-{args.horizon})")

    clean_predict = report_training_boundary(frame, horizon=args.horizon, buffer=0)
    clean_internal = report_internal_split(frame, horizon=args.horizon, buffer=0)
    report_buffer(frame, horizon=args.horizon)

    print("\n" + "=" * 78)
    print("Urteil")
    print("=" * 78)
    print(
        f"\n  Training -> Vorhersage        {'sauber' if clean_predict else 'LECK'}\n"
        f"  Training -> int. Validierung  {'sauber' if clean_internal else 'LECK'}\n"
    )
    print(
        "  Die pauschale Aussage des Zustandsberichts -- 'FreqAI hat kein Purging\n"
        "  und kein Embargo' -- ist damit zu grob. Die erste Grenze schuetzt sich\n"
        "  durch den Shift selbst. Die zweite ist ungeschuetzt, und das ist die,\n"
        "  an der Early Stopping und die Test-Kennzahlen haengen.\n"
        "\n  Konsequenz fuer dieses Projekt: `data_split_parameters.test_size = 0`\n"
        "  schaltet die interne Teilung ab (siehe `make_train_test_datasets`), und\n"
        "  die Auswahl gehoert dann in den aeusseren, zeitlich korrekten\n"
        "  Walk-forward. Alte FreqAI-Laeufe mit test_size > 0 bleiben als\n"
        "  eingeschraenkt interpretierbar markiert -- ein Parameter im Nachhinein\n"
        "  gibt keinen vergangenen Lauf frei."
    )
    return 0 if clean_predict else 1


if __name__ == "__main__":
    sys.exit(main())
