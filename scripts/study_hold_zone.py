"""E2: Rechtfertigt der erwartete Gewinn einen POSITIONSWECHSEL?

    python scripts/study_hold_zone.py
    python scripts/study_hold_zone.py --symbols BTCUSDT,ETHUSDT --horizon 1

Registriert als E2 in `audit/EXPERIMENTS_NEXT.yaml`, fünf Arme, acht Vergleiche,
vorab festgelegt.

## Die Unterscheidung, um die es geht

Der vorhandene Kostenfilter fragt: *"ist die runde Fahrt klein gegen das
riskierte Geld?"* Das ist etwas anderes als: *"rechtfertigt der erwartete
Gewinn, dass ich die Position ändere?"*

Der Unterschied ist nicht akademisch, er ist die ganze Rechnung. Eine
bestehende Position zu **halten** kostet keine runde Fahrt. Wer jede Kerze die
volle Maut gegen den Forecast stellt, verwirft Positionen, die zu halten gratis
gewesen wäre -- und bezahlt dafür mit dem Wechsel, den er stattdessen macht.

Also:

* **Naive Vorzeichenentscheidung:** Forecast > 0 -> long, sonst flat. Jeder
  Wechsel kostet, und sie wechselt oft.
* **Kostenbewusste Zone:** wechsle nur, wenn der erwartete Gewinn die
  **zusätzlichen** Kosten des Wechsels um einen vorab festgelegten Faktor
  übersteigt. Dazwischen liegt eine Haltezone, in der die bestehende Position
  bleibt, was sie ist.

## Was hier gegen was gemessen wird

Die Abnahme aus der Registrierung verlangt beides, und das zweite ist das
härtere: Vorteil gegen **denselben ungefilterten Forecast** (sonst misst man
das Modell und nicht die Zone) **und** absolute Nettoleistung. Dazu getrennt
die Beurteilung gegen passives Halten -- ein Arm, der long/flat schaltet und
dabei schlechter ist als einfach liegenzubleiben, hat nichts gewonnen.

## Zwei Dinge, die bewusst klein gehalten sind

**Nur zwei Modelle, beide einfach.** Eine Ridge-Regression, von Hand
geschrieben, damit die Standardisierung nur aus dem Trainingsfenster kommt --
ein unachtsames `fit_transform` über alles ist genau das Leck, das der
Forschungsauftrag in Punkt 7 nennt. Und ein flaches XGBoost mit vorab
fixierter Komplexität. Keine Transformer, und keine Parametersuche: 124
Versuche im Register sagen, dass das Problem nicht die Suche ist.

**Eine Hauptschwelle, drei angemeldete Sensitivitäten.** Die Hauptschwelle
steht in `PRIMARY_THRESHOLD`, bevor eine Zahl gelesen wurde. Die anderen drei
zählen in die 46 Vergleiche und werden nicht als "die beste" berichtet.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover
    xgb = None

from traidingbrain.domain.market import DEFAULT_SPEC
from traidingbrain.reporting.intervals import block_bootstrap

OHLCV = ROOT / "data" / "ohlcv"

#: Eine Richtung kostet die halbe Runde. Aus der Projekt-Spezifikation, nicht
#: hier erfunden -- ein Wechsel ist ein Ausstieg plus ein Einstieg.
ONE_WAY = DEFAULT_SPEC["maker_fee"] + DEFAULT_SPEC["taker_fee"]

#: Die Hauptschwelle: ein Wechsel muss diesen Faktor seiner eigenen
#: Zusatzkosten an erwartetem Gewinn versprechen. Vorab festgelegt.
PRIMARY_THRESHOLD = 1.5

#: Angemeldete Sensitivitaeten. Sie zaehlen in die 46 Vergleiche und werden
#: nicht als "die beste Schwelle" berichtet.
SENSITIVITIES = (1.0, 2.0, 3.0)

#: Zeitfenster als Anteile, auf Zeitstempeln geschnitten. Das innere Fenster
#: darf exploriert werden, das letzte entscheidet.
TRAIN_SHARE = 0.60
DEVELOP_SHARE = 0.20

#: Rueckblickfenster der Merkmale, in H1-Kerzen. Alle backward-looking.
LOOKBACKS = (1, 6, 24, 72)
VOL_WINDOW = 24

#: Vorab fixierte Komplexitaet. Nicht nach dem Ergebnis angepasst.
XGB_FIXED = {
    "n_estimators": 150,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 2.0,
    "verbosity": 0,
}

#: Mehrfachkorrektur ueber die in EXPERIMENTS_NEXT.yaml angemeldeten Zellen.
TOTAL_COMPARISONS = 46
CORRECTED = 1.0 - 0.05 / TOTAL_COMPARISONS

SEED = 20261007


def load_h1(symbol: str) -> pd.DataFrame:
    files = sorted((OHLCV / symbol / "H1").glob("*.parquet"))
    if not files:
        raise SystemExit(f"Keine H1-Daten fuer {symbol}.")
    frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    frame["ts"] = frame["ts"].astype("int64")
    return frame.drop_duplicates(subset="ts", keep="first").sort_values("ts").reset_index(drop=True)


def build(symbol: str, *, horizon: int) -> pd.DataFrame:
    """Merkmale und Ziel, und die eine Verschiebung, die alles entscheidet.

    **Hier steckte am 07.10.2026 ein Leck, und es war gross.** Die erste
    Fassung berechnete jedes Merkmal aus `close[t]` und das Ziel als
    `open[t+1]/open[t]`. Auf H1 ist `open[t+1]` praktisch `close[t]` und
    `open[t]` praktisch `close[t-1]` -- also war das Merkmal `ret_1` das Ziel.
    Gemessene Korrelation: **+0,9999**. Das Modell bekam die Antwort gereicht
    und meldete +1018 % netto.

    Um eine Kerze verschoben, also nur mit Daten bis `close[t-1]`, faellt
    dieselbe Korrelation auf **-0,0059**.

    Die Regel dahinter ist die, die `panel.daily_prices` schon traegt: eine
    Entscheidung, die bei `open[t]` ausgefuehrt wird, darf nur wissen, was bis
    `close[t-1]` geschehen ist. `close[t]` liegt NACH `open[t]` -- ein Merkmal
    daraus kennt die Kerze, die es handelt.

    `_assert_no_leak` prueft das danach an den gebauten Spalten, statt sich auf
    diesen Kommentar zu verlassen.
    """
    frame = load_h1(symbol)
    close = frame["close"]
    raw = pd.DataFrame(index=frame.index)
    for back in LOOKBACKS:
        raw[f"ret_{back}"] = close / close.shift(back) - 1.0
    returns = close / close.shift(1) - 1.0
    raw["vol"] = returns.rolling(VOL_WINDOW).std()
    raw["range"] = (frame["high"] - frame["low"]).rolling(VOL_WINDOW).mean() / close
    raw["vol_ratio"] = frame["volume"] / frame["volume"].rolling(VOL_WINDOW).mean()

    out = pd.DataFrame({"ts": frame["ts"]})
    # DIE Verschiebung: Zeile t traegt den Stand vom Ende der Kerze t-1.
    for column in raw.columns:
        out[column] = raw[column].shift(1)

    # Das einzige shift(-n). Open-to-open, damit der Einstieg ein Preis ist,
    # den eine Entscheidung am Ende der Vorkerze erreichen konnte.
    entry = frame["open"]
    out["target"] = entry.shift(-horizon) / entry - 1.0
    out["entry"] = entry
    return out.dropna().reset_index(drop=True)


def assert_no_leak(data: pd.DataFrame, names: list[str], *, limit: float = 0.2) -> None:
    """Kein Merkmal darf mit dem Ziel fast identisch sein.

    Eine Korrelation nahe eins ist kein starkes Merkmal, sondern das Ziel unter
    anderem Namen. Die Schwelle ist bewusst niedrig: in diesem Projekt liegt
    jede ehrliche Merkmalskorrelation bei wenigen Tausendsteln, also ist alles
    ueber 0,2 ein Alarm und keine Entdeckung.
    """
    target = data["target"].to_numpy()
    for name in names:
        values = data[name].to_numpy()
        if values.std() == 0:
            continue
        correlation = float(np.corrcoef(values, target)[0, 1])
        if abs(correlation) > limit:
            raise SystemExit(
                f"'{name}' korreliert zu {correlation:+.4f} mit dem Ziel. Das ist kein\n"
                f"Merkmal, das ist das Ziel. Pruefe die Verschiebung in `build`."
            )


@dataclass(frozen=True, slots=True)
class Arm:
    name: str
    net: float
    gross: float
    switches: int
    cost: float
    exposure: float
    #: Netto-Rendite je Kerze, als Folge -- die Grundlage des Intervalls.
    per_bar: np.ndarray = field(default_factory=lambda: np.array([]))
    low: float = float("nan")
    high: float = float("nan")

    @property
    def proven(self) -> bool:
        """Intervall ganz ueber der Null, auf das korrigierte Niveau gerechnet.

        Ohne das ist "netto positiv" eine Punktschaetzung, und eine
        Punktschaetzung ist in diesem Projekt genau die Form, in der acht
        Scheinfunde angefangen haben.
        """
        return self.low > 0.0


def ridge(train_x: np.ndarray, train_y: np.ndarray, *, penalty: float = 1.0) -> np.ndarray:
    """Ridge in geschlossener Form, standardisiert NUR auf dem Trainingsfenster.

    Von Hand, weil die Standardisierung sonst leicht aus allen Daten kommt und
    das Leck dann unsichtbar in einer Bibliotheksfunktion sitzt.
    """
    mean, scale = train_x.mean(axis=0), train_x.std(axis=0)
    scale[scale == 0] = 1.0
    z = (train_x - mean) / scale
    z = np.column_stack([np.ones(len(z)), z])
    ridge_matrix = penalty * np.eye(z.shape[1])
    ridge_matrix[0, 0] = 0.0  # den Achsenabschnitt nicht bestrafen
    weights = np.linalg.solve(z.T @ z + ridge_matrix, z.T @ train_y)
    return np.concatenate([weights, mean, scale])


def ridge_predict(x: np.ndarray, packed: np.ndarray) -> np.ndarray:
    k = x.shape[1]
    weights, mean, scale = packed[: k + 1], packed[k + 1 : 2 * k + 1], packed[2 * k + 1 :]
    z = (x - mean) / scale
    return np.column_stack([np.ones(len(z)), z]) @ weights


def named(label: str, arm: Arm) -> Arm:
    """Einen Arm benennen und sein Intervall rechnen.

    Das Intervall ist nicht Zierde: ohne es ist "netto positiv" eine
    Punktschaetzung. Dieser Lauf hat dafuer ein frisches Beispiel -- die
    Haltezone auf XGBoost las +0.12% ueber ein Jahr auf 27 Wechseln, und die
    angemeldeten Schwellen-Sensitivitaeten spannten +0.12% bis +40.57%. Eine
    Zahl, die so stark an der Schwelle haengt, braucht ihre Unsicherheit
    neben sich.

    Gerechnet auf dem korrigierten Niveau fuer die 46 angemeldeten Vergleiche,
    in Bloecken: benachbarte Stunden sind nicht unabhaengig, und eine Position
    laeuft ueber viele davon.
    """
    interval = block_bootstrap(arm.per_bar.tolist(), level=CORRECTED)
    return Arm(
        label,
        arm.net,
        arm.gross,
        arm.switches,
        arm.cost,
        arm.exposure,
        arm.per_bar,
        interval.low * arm.per_bar.size if interval is not None else float("nan"),
        interval.high * arm.per_bar.size if interval is not None else float("nan"),
    )


def walk(forecast: np.ndarray, realised: np.ndarray, *, threshold: float | None) -> Arm:
    """Ein Positionspfad, und was er netto einbringt.

    `threshold=None` ist die naive Vorzeichenentscheidung: jede Kerze neu, ohne
    Rücksicht auf die Kosten des Wechsels.

    Mit Schwelle gilt die Haltezone: gewechselt wird nur, wenn der Forecast die
    **zusätzlichen** Kosten des Wechsels um `threshold` übersteigt. Und
    entscheidend -- eine bestehende Position zu halten kostet nichts, also wird
    die Maut nur beim Wechsel verbucht und nicht je Kerze.
    """
    position = 0.0
    gross = 0.0
    cost = 0.0
    switches = 0
    held = 0
    # Je Kerze, damit ein Blockbootstrap daraus ein Intervall machen kann.
    per_bar = np.zeros(forecast.size)
    for step in range(forecast.size):
        wanted = 1.0 if forecast[step] > 0.0 else 0.0
        if threshold is not None and wanted != position:
            # Was der Wechsel kostet: raus aus der alten, rein in die neue.
            # Von flat nach long ist ein Einstieg, umgekehrt ein Ausstieg.
            switch_cost = ONE_WAY
            if abs(forecast[step]) < threshold * switch_cost:
                wanted = position  # in der Haltezone bleibt alles, wie es ist
        switched = wanted != position
        if switched:
            cost += ONE_WAY
            switches += 1
            position = wanted
        step_cost = ONE_WAY if switched else 0.0
        step_gross = position * realised[step]
        per_bar[step] = step_gross - step_cost
        gross += step_gross
        held += int(position > 0.0)
    return Arm(
        "", gross - cost, gross, switches, cost, held / max(1, forecast.size), per_bar
    )


def one_market(symbol: str, *, horizon: int) -> None:
    """Ein Markt: bauen, pruefen, rechnen, urteilen.

    Getrennt von `main`, damit die Leckpruefung und die Abnahme nebeneinander
    lesbar bleiben -- die beiden Stellen, an denen dieser Lauf einmal falsch
    war und einmal zu grosszuegig.
    """
    data = build(symbol, horizon=horizon)
    names = [c for c in data.columns if c not in ("ts", "target", "entry")]
    assert_no_leak(data, names)
    n = len(data)
    train_end = int(n * TRAIN_SHARE)
    develop_end = int(n * (TRAIN_SHARE + DEVELOP_SHARE))
    # Purge um den Zielhorizont, damit das letzte Trainingslabel nicht in
    # das naechste Fenster reicht.
    train = data.iloc[: train_end - horizon]
    confirm = data.iloc[develop_end + horizon :]

    x_train = train[names].to_numpy()
    y_train = train["target"].to_numpy()
    x_confirm = confirm[names].to_numpy()
    y_confirm = confirm["target"].to_numpy()

    first = pd.Timestamp(int(confirm["ts"].iloc[0]), unit="ms", tz="UTC").date()
    last = pd.Timestamp(int(confirm["ts"].iloc[-1]), unit="ms", tz="UTC").date()
    print(f"{symbol}  {n:,} Kerzen, Bestaetigungsfenster {first} bis {last} "
          f"({len(confirm):,} Kerzen)")

    arms: list[Arm] = []
    models: list[tuple[str, np.ndarray]] = [
        ("Ridge", ridge_predict(x_confirm, ridge(x_train, y_train)))
    ]
    if xgb is None:
        # Ein stillschweigend fehlender Arm macht eine Vorab-Registrierung
        # wertlos: die Mehrfachkorrektur zaehlt dann Zellen, die nie
        # gelaufen sind. Also laut, und als nicht testbar vermerkt.
        print(
            "  ! XGBoost ist im Projekt-venv nicht installiert. E2.3 und E2.4\n"
            "    laufen NICHT und sind als nicht testbar zu registrieren --\n"
            "    nicht als Zellen, die nichts gefunden haben."
        )
    else:
        tree = xgb.XGBRegressor(**XGB_FIXED, random_state=SEED)
        tree.fit(x_train, y_train)
        models.append(("XGBoost", tree.predict(x_confirm)))

    for label, forecast in models:
        naive = walk(forecast, y_confirm, threshold=None)
        arms.append(named(f"{label}, naiv", naive))
        zone = walk(forecast, y_confirm, threshold=PRIMARY_THRESHOLD)
        arms.append(named(f"{label}, Haltezone {PRIMARY_THRESHOLD}x", zone))

    # Passives Halten: immer long, ein Einstieg, ein Ausstieg.
    passive_bars = y_confirm.copy()
    passive_bars[0] -= ONE_WAY
    passive_bars[-1] -= ONE_WAY
    arms.append(
        named(
            "passiv long",
            Arm("", float(passive_bars.sum()), float(y_confirm.sum()), 2,
                2 * ONE_WAY, 1.0, passive_bars),
        )
    )

    print(
        f"  {'Arm':30s} {'netto':>9s} {'brutto':>9s} {'Wechsel':>8s} "
        f"{'Maut':>9s} {'im Markt':>9s}  korrigiertes Intervall"
    )
    print("  " + "-" * 104)
    for arm in arms:
        mark = " *" if arm.proven else ""
        print(
            f"  {arm.name:30s} {100 * arm.net:>+8.2f}% {100 * arm.gross:>+8.2f}% "
            f"{arm.switches:>8d} {100 * arm.cost:>8.2f}% {100 * arm.exposure:>8.1f}%"
            f"  [{100 * arm.low:+.2f}, {100 * arm.high:+.2f}]{mark}"
        )

    print("\n  Angemeldete Sensitivitaeten der Schwelle:")
    for label, forecast in models:
        cells = []
        for threshold in SENSITIVITIES:
            arm = walk(forecast, y_confirm, threshold=threshold)
            cells.append(f"{threshold:.1f}x {100 * arm.net:>+7.2f}%")
        print(f"    {label:10s} " + "  ".join(cells))

    print("\n  " + "-" * 80)
    best_zone = max((a for a in arms if "Haltezone" in a.name), key=lambda a: a.net)
    best_naive = max((a for a in arms if "naiv" in a.name), key=lambda a: a.net)
    passive = arms[-1]
    print(
        f"  Abnahme, vorab festgelegt:\n"
        f"    (a) absolut netto positiv, INTERVALL ohne Null: "
        f"{'JA' if best_zone.proven else 'NEIN'} "
        f"({100 * best_zone.net:+.2f}% [{100 * best_zone.low:+.2f}, "
        f"{100 * best_zone.high:+.2f}])\n"
        f"    (b) besser als derselbe Forecast ohne Zone: "
        f"{'JA' if best_zone.net > best_naive.net else 'NEIN'} "
        f"({100 * best_zone.net:+.2f}% gegen {100 * best_naive.net:+.2f}%)\n"
        f"    (c) besser als passives Halten: "
        f"{'JA' if best_zone.net > passive.net else 'NEIN'} "
        f"({100 * best_zone.net:+.2f}% gegen {100 * passive.net:+.2f}%)"
    )
    # (a) verlangt das Intervall, nicht den Punktwert. Eine erste Fassung
    # dieses Skripts verlangte nur `net > 0` und meldete damit +0.12% ueber
    # ein Jahr auf 27 Wechseln als Kandidaten.
    passed = (
        best_zone.proven
        and best_zone.net > best_naive.net
        and best_zone.net > passive.net
    )
    print(f"    -> {'KANDIDAT' if passed else 'NICHT BELEGT'}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--horizon", type=int, default=1)
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print("=" * 100)
    print("E2 -- rechtfertigt der erwartete Gewinn einen Positionswechsel?")
    print("=" * 100)
    print(
        f"\nKosten einer Richtung: {100 * ONE_WAY:.4f}%  "
        f"(ein Wechsel ist ein Ausstieg plus ein Einstieg)"
    )
    print(f"Hauptschwelle: {PRIMARY_THRESHOLD}x die Zusatzkosten des Wechsels")
    print(f"Horizont: {args.horizon} H1-Kerze(n)\n")

    for symbol in symbols:
        one_market(symbol, horizon=args.horizon)

    print("-" * 100)
    print(
        "  Was dieser Lauf zeigt, ganz unabhaengig vom Urteil: die Haltezone spart\n"
        "  Maut, und sie spart sie in der Groessenordnung, in der die Maut hier\n"
        "  ueberhaupt entscheidet. Was sie NICHT kann, ist einen Forecast retten,\n"
        "  der die Richtung nicht trifft -- eine Zone ohne Vorhersage waehlt nur\n"
        "  seltener falsch.\n"
        "\n  Und was hier fehlt: ein vollstaendiges Portfolio. Dieser Lauf ist ein\n"
        "  Markt zur Zeit, immer voll investiert oder flach, ohne Slot-Konkurrenz\n"
        "  und ohne Margin. Das ist die Signalfrage, nicht die Kontofrage."
    )
    print("-" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
