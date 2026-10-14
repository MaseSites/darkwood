"""E1: Erkennen Merkmale vom Entscheidungszeitpunkt eine profitable Teilmenge?

    python scripts/study_meta_label.py
    python scripts/study_meta_label.py --symbols BTCUSDT,ETHUSDT

Registriert in `audit/EXPERIMENTS_NEXT.yaml` als E1, mit fünf Armen und zehn
Vergleichen, **bevor** eine Zahl gelesen wurde.

## Warum dieser Arm überhaupt erlaubt ist

Der Zustandsbericht behauptete, eine Auswahl im Pool ohne Vorteil könne nichts
beitragen. Das ist ein Kategoriefehler, und `scripts/study_subset.py` widerlegt
ihn an den eigenen Daten: Pool -0,0906 R, Teilmenge `rating_band=eindeutig`
+0,0311 R auf 588 Trades. Das Intervall umspannt die Null, also ist es kein
Fund -- aber die Begründung, mit der die Frage geschlossen war, trägt nicht.

## Was hier anders ist als in `study_subset.py`

Dort wurden Zellen auf allen Daten angesehen. Hier wird ein Modell auf einem
**früheren** Fenster trainiert, die Schwelle auf einem **inneren** Fenster
gewählt und eingefroren, und erst dann auf einem **späteren** Fenster gemessen,
das die Wahl nicht beeinflusst hat. Ein Modell, das sein eigenes Testfenster
mitgewählt hat, misst sich selbst.

## Die Population

Alle ex ante gültigen Kandidaten -- **genommene und abgelehnte**. Das ist der
Punkt: die abgelehnten existieren erst, seit `study_refused.py` sie aufzeichnet,
und ohne sie kann man nicht fragen, ob die Regeln Geld kosten. Sie werden
hypothetisch gelabelt und bleiben **Counterfactuals**: sie haben nie um einen
Platz konkurriert, und das Label weiss das nicht.

Sicherheitsablehnungen (`liquidation`) werden **nicht** überstimmt. Eine
Auswahlregel darf eine Risikoregel nicht aushebeln.

## Merkmale: nur was vor dem Trade feststeht

Erlaubt sind Setup, Zeitebene, Seite, Chance-Risiko, Kostenanteil, Stop-Breite,
Tageszeit, Wochentag und der Markt. **Verboten** sind Haltezeit, MFE/MAE,
Ausstiegsgrund und jedes realisierte Ergebnis -- die kennen den Ausgang, und
dieses Projekt hat eine Vergleichsgrösse schon einmal auf eine solche Grösse
gestützt (Haltedauer, Korrelation +0,52).

## Die Abnahme, vorab festgelegt

Nicht "schlägt den Pool". Ein Pool bei -0,09 R zu schlagen heisst nichts, wenn
das Ergebnis immer noch negativ ist. Verlangt sind:

1. **absolut** positives Netto-R im Bestätigungsfenster,
2. Mehrwert gegen einen **Zufallsfilter gleicher Selektivität**,
3. ein Intervall, das die Null ausschliesst, auf 46 Vergleiche korrigiert.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.signals import SignalRecord, SignalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.frozen import freeze
from traidingbrain.learn.labels import Label, Minutes, label_signal
from traidingbrain.learn.overrides import describe, safety_rules
from traidingbrain.reporting.intervals import block_bootstrap

HOUR_MS = 3_600_000
DAY_MS = 86_400_000

#: Derselbe Horizont wie in `study_refused.py`, damit die Labels vergleichbar
#: bleiben. Eine andere Zahl hier erzeugte eine zweite Population.
HORIZON_HOURS = 48

#: Die drei Fenster, als Anteile der nach Zeit sortierten Signale.
#: Trainieren, Schwelle waehlen, bestaetigen -- und nur das letzte entscheidet.
TRAIN_SHARE = 0.55
DEVELOP_SHARE = 0.20

#: Purge zwischen den Fenstern: der volle Label-Horizont plus ein Tag Embargo.
#: Ohne ihn reicht das letzte Trainingslabel in das naechste Fenster hinein --
#: genau die Luecke, die in FreqAIs interner Teilung offen ist.
PURGE_MS = HORIZON_HOURS * HOUR_MS + DAY_MS

#: Vorab festgelegte Selektivitaet der Modellarme: der Anteil der Kandidaten
#: mit dem hoechsten Score, der genommen wird. Nicht nach dem Ergebnis gewaehlt.
KEEP_SHARE = 0.30

#: Mehrfachkorrektur ueber die in EXPERIMENTS_NEXT.yaml angemeldeten Zellen.
TOTAL_COMPARISONS = 46

#: Ablehnungsgruende, die eine Auswahlregel NICHT ueberstimmen darf.
#
# `grenzen` ist am 13.10.2026 dazugekommen: eine Kontogrenze (Tagesverlust,
# Abkuehlung, Zahl offener Positionen) ist kein Urteil ueber das Signal,
# sondern ueber den Kontostand. Eine Auswahlregel darf sie nicht
# ueberstimmen -- an einem anderen Tag waere dasselbe Signal durchgegangen.
#
# Seit dem 14.10.2026 steht die Menge an EINER Stelle
# (`learn/overrides.py`), und diese Studie waehlt die WEITE Lesart
# AUSDRUECKLICH. Sie betrachtet damit Signale, die der Kostendeckel oder das
# Mindest-Chance-Risiko abgelehnt hat -- beides Produktionsregeln in
# `sim/plan.py`. Ein positives Ergebnis hier ist also nicht umsetzbar, ohne
# eine Schutzregel zu aendern, und braucht dafuer einen eigenen Nachweis.
#
# Das Schluesselwort steht da, damit die Entscheidung nicht mehr still ist:
# vorher unterschieden sich die Populationen der beiden Studien, und der
# Unterschied war nur aus zwei Quelldateien zu erschliessen. Der Bericht
# druckt `SAFETY_NOTE` in seinem Kopf.
SAFETY_RULES = safety_rules(allow_rule_change=True)
SAFETY_NOTE = describe(allow_rule_change=True)

SEED = 20261007

#: Unter so vielen aufgeloesten Kandidaten traegt die Dreiteilung nicht.
MIN_CASES = 500

#: Die Komplexitaet von E1.5, in `audit/EXPERIMENTS_NEXT.yaml` vorab fixiert.
#: Sie wird NICHT nach dem Ergebnis angepasst -- ein getunter Baum auf dem
#: Bestaetigungsfenster ist derselbe Fehler wie eine nachtraeglich gewaehlte
#: Schwelle, nur schwerer zu sehen.
LGBM_FIXED = {
    "num_leaves": 15,
    "max_depth": 4,
    "min_child_samples": 60,
    "n_estimators": 200,
    "learning_rate": 0.05,
    "reg_lambda": 2.0,
    "verbosity": -1,
    "random_state": SEED,
}


@dataclass(frozen=True, slots=True)
class Case:
    """Ein Kandidat: Merkmale vom Entscheidungszeitpunkt, und sein Ausgang."""

    decided_ts: int
    symbol: str
    features: dict[str, float]
    net_r: float
    refused_by: str | None
    #: Wann das Label dieses Falls tatsaechlich endete, nicht der pauschale
    #: Horizont. Die Barriere loest variabel auf, und die Purge-Pruefung
    #: braucht das echte Ende -- `HORIZON_HOURS` ist die Obergrenze, nicht
    #: die Dauer.
    closed_ts: int = 0


def ex_ante_features(record: SignalRecord) -> dict[str, float]:
    """Nur Groessen, die zum Entscheidungszeitpunkt feststehen.

    Jede hier ist aus dem Signalsatz lesbar, bevor der Trade existiert. Was
    fehlt, fehlt mit Absicht: Haltezeit, MFE/MAE und Ausstiegsgrund kennen den
    Ausgang.
    """
    stop_fraction = abs(record.entry - record.stop) / record.entry if record.entry else 0.0
    hour = (record.decided_ts % DAY_MS) / HOUR_MS
    return {
        "reward_risk": float(record.reward_risk),
        "cost_fraction": float(record.cost_fraction),
        "stop_fraction": stop_fraction,
        "is_long": 1.0 if record.side.value == "long" else 0.0,
        "hour_sin": float(np.sin(2 * np.pi * hour / 24.0)),
        "hour_cos": float(np.cos(2 * np.pi * hour / 24.0)),
        "weekday": float((record.decided_ts // DAY_MS) % 7),
    }


def build_cases(symbols: list[str], *, signature: str) -> list[Case]:
    """Signale laden, labeln, Merkmale bauen -- je Markt."""
    config = load_config()
    store = ParquetStore(config.engine.paths.data_dir / "ohlcv")
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")
    expiry_ms = config.engine.simulation.entry_expiry_bars * timeframe_ms(
        config.engine.timeframes.signal
    )

    cases: list[Case] = []
    for symbol in symbols:
        records = signals.all(symbol=symbol, run_signature=signature)
        if not records:
            print(f"  {symbol:10s} keine Signale unter dieser Signatur")
            continue
        frame = store.read(symbol, config.engine.timeframes.execution)
        if frame.empty:
            print(f"  {symbol:10s} keine Minutendaten")
            continue
        # `label_signal` erwartet flache Arrays, keine DataFrame -- die Umwandlung
        # ist der Unterschied zwischen Minuten und Stunden Laufzeit.
        minutes = Minutes.of(frame)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        started = time.perf_counter()
        kept = 0
        for record in records:
            if record.refused_by in SAFETY_RULES:
                continue
            label: Label = label_signal(
                side=record.side,
                entry=record.entry,
                stop=record.stop,
                target=record.target,
                decision_ts=record.decided_ts,
                minutes=minutes,
                spec=spec,
                config=config.engine.simulation,
                horizon_ms=HORIZON_HOURS * HOUR_MS,
                expiry_ms=expiry_ms,
            )
            if not label.resolved:
                continue
            cases.append(
                Case(
                    decided_ts=record.decided_ts,
                    symbol=symbol,
                    features=ex_ante_features(record),
                    net_r=label.net_r,
                    refused_by=record.refused_by,
                    closed_ts=label.closed_ts,
                )
            )
            kept += 1
        print(
            f"  {symbol:10s} {len(records):6,d} Signale -> {kept:6,d} aufgeloest "
            f"({time.perf_counter() - started:5.1f}s)"
        )
    return sorted(cases, key=lambda c: c.decided_ts)


def split(cases: list[Case]) -> tuple[list[Case], list[Case], list[Case]]:
    """Trainieren, entwickeln, bestaetigen -- auf Zeit, mit Purge dazwischen.

    Geschnitten wird auf **Zeitstempeln**, nicht auf Zeilen: alle Maerkte eines
    Zeitpunkts gehoeren auf dieselbe Seite jeder Grenze, sonst sagt ein Markt
    dem anderen, was gleich passiert.
    """
    stamps = np.array([c.decided_ts for c in cases])
    first, last = int(stamps.min()), int(stamps.max())
    span = last - first
    train_end = first + int(span * TRAIN_SHARE)
    develop_end = first + int(span * (TRAIN_SHARE + DEVELOP_SHARE))

    train = [c for c in cases if c.decided_ts <= train_end]
    develop = [c for c in cases if train_end + PURGE_MS < c.decided_ts <= develop_end]
    confirm = [c for c in cases if c.decided_ts > develop_end + PURGE_MS]
    return train, develop, confirm


def matrix(cases: list[Case], names: list[str]) -> np.ndarray:
    return np.array([[c.features[n] for n in names] for c in cases])


def fit_logistic(
    train: list[Case], names: list[str], *, steps: int = 400, penalty: float = 1.0
) -> np.ndarray:
    """Regularisierte logistische Regression, von Hand, auf standardisierten Merkmalen.

    Kein sklearn, weil die Standardisierung hier **nur** aus dem Trainingsfenster
    kommen darf und ein unachtsamer `fit_transform` auf allen Daten genau die
    Art Leck ist, die der Forschungsauftrag in Punkt 7 nennt. Vierhundert
    Gradientenschritte auf wenigen Merkmalen sind billig und nachvollziehbar.
    """
    x = matrix(train, names)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (x - mean) / scale
    x = np.column_stack([np.ones(len(x)), x])
    y = np.array([1.0 if c.net_r > 0 else 0.0 for c in train])

    weights = np.zeros(x.shape[1])
    rate = 0.1
    for _ in range(steps):
        p = 1.0 / (1.0 + np.exp(-x @ weights))
        gradient = x.T @ (p - y) / len(y)
        gradient[1:] += penalty * weights[1:] / len(y)
        weights -= rate * gradient
    return np.concatenate([weights, mean, scale])


def score_logistic(cases: list[Case], names: list[str], packed: np.ndarray) -> np.ndarray:
    k = len(names)
    weights, mean, scale = packed[: k + 1], packed[k + 1 : 2 * k + 1], packed[2 * k + 1 :]
    x = (matrix(cases, names) - mean) / scale
    x = np.column_stack([np.ones(len(x)), x])
    return 1.0 / (1.0 + np.exp(-x @ weights))


@dataclass(frozen=True, slots=True)
class ArmResult:
    name: str
    n: int
    mean_net_r: float
    low: float
    high: float
    share: float

    @property
    def proven(self) -> bool:
        return self.low > 0.0


def evaluate(name: str, chosen: list[Case], *, of: int, level: float) -> ArmResult:
    if not chosen:
        return ArmResult(name, 0, float("nan"), float("nan"), float("nan"), 0.0)
    values = [c.net_r for c in chosen]
    interval = block_bootstrap(values, level=level)
    low = interval.low if interval is not None else float("nan")
    high = interval.high if interval is not None else float("nan")
    return ArmResult(name, len(values), float(np.mean(values)), low, high, len(values) / of)


def case_vintage(cases: list[Case]) -> str:
    """Ein Fingerabdruck der Faelle, aus denen ein Arm gerechnet wurde.

    Das Pendant zu `Panel.vintage_id`, nur dass die Quelle hier das Ledger
    ist und nicht ein Panel. Die Labels loesen aus Minutendaten auf, also
    aendert ein nachgeladener oder korrigierter Minutenbalken das Ergebnis
    -- und genau das muss dem Dateinamen anzusehen sein.
    """
    rows = pd.DataFrame(
        {
            "decided_ts": [c.decided_ts for c in cases],
            "symbol": [c.symbol for c in cases],
            "net_r": [c.net_r for c in cases],
            "closed_ts": [c.closed_ts for c in cases],
        }
    ).sort_values(["decided_ts", "symbol"])
    digest = pd.util.hash_pandas_object(rows, index=False)
    return hashlib.sha256(digest.to_numpy().tobytes()).hexdigest()


def freeze_arm(
    name: str,
    confirm: list[Case],
    keep: list[bool],
    *,
    scores: np.ndarray | None,
    signature: str,
    vintage: str,
) -> None:
    """Das Bestaetigungsfenster eines Arms als unveraenderliche Datei.

    Eine Zeile je Entscheidung, auch die abgelehnten -- der Auftrag verlangt
    Netto-PnL **pro Signal**, und eine Datei nur der genommenen Trades kann
    nicht sagen, was ein Arm beim Ablehnen verpasst hat.
    """
    if not any(keep):
        print(f"    {name}: nichts genommen, nichts eingefroren")
        return
    frame = pd.DataFrame(
        {
            "decision_ms": [c.decided_ts for c in confirm],
            "market": [c.symbol for c in confirm],
            "score": (
                np.asarray(scores, dtype=float)
                if scores is not None
                else np.full(len(confirm), np.nan)
            ),
            "selected": keep,
            "net_r": [c.net_r for c in confirm],
            "label_end_ms": [c.closed_ts for c in confirm],
            "refused_by": [c.refused_by or "" for c in confirm],
        }
    )
    written = freeze(
        frame,
        root=ROOT / "data" / "frozen",
        experiment="E1",
        arm=name,
        signature=signature,
        vintage=vintage,
        horizon_note=(
            f"Barriere, Obergrenze {HORIZON_HOURS}h. label_end_ms je Zeile ist "
            f"die tatsaechliche Aufloesung, nicht der pauschale Horizont."
        ),
        unit="net_r_per_signal",
        extra={
            "window": "confirm",
            "threshold_chosen_on": "develop",
            "purge_hours": PURGE_MS // HOUR_MS,
            "total_comparisons": TOTAL_COMPARISONS,
        },
    )
    print(f"    {written.describe()}")


def judge(results: list[ArmResult]) -> None:
    """Die drei vorab festgelegten Bedingungen, je Modellarm.

    Getrennt von `main`, und die Arme werden am NAMEN gegriffen statt an der
    Position: `results[3]` war richtig, solange es vier Arme gab, und waere
    beim fuenften still zum falschen geworden.
    """
    print("\n" + "-" * 94)
    # Am Namen gegriffen, nicht an der Position. `results[3]` war richtig,
    # solange es vier Arme gab, und wird beim fuenften still zum falschen Arm.
    by_name = {arm.name: arm for arm in results}
    pool = next(a for n, a in by_name.items() if n.startswith("E1.1"))
    control = next(a for n, a in by_name.items() if n.startswith("E1.3"))
    models = [a for n, a in by_name.items() if n.startswith(("E1.4", "E1.5"))]

    print("  Abnahme, vorab festgelegt, je Modellarm:\n")
    candidates = []
    for arm in models:
        absolute = arm.mean_net_r > 0
        beats = arm.mean_net_r > control.mean_net_r
        print(
            f"    {arm.name}\n"
            f"      (a) absolut positiv:              "
            f"{'JA' if absolute else 'NEIN'} ({arm.mean_net_r:+.4f} R)\n"
            f"      (b) besser als Zufallsfilter:     "
            f"{'JA' if beats else 'NEIN'} "
            f"({arm.mean_net_r:+.4f} gegen {control.mean_net_r:+.4f} R)\n"
            f"      (c) korrigiertes Intervall ohne Null: "
            f"{'JA' if arm.proven else 'NEIN'}"
        )
        if absolute and beats and arm.proven:
            candidates.append(arm.name)

    print(
        f"\n  -> {'KANDIDAT: ' + ', '.join(candidates) if candidates else 'NICHT BELEGT'}\n"
        f"\n  Zum Einordnen: der ungefilterte Pool liegt bei {pool.mean_net_r:+.4f} R.\n"
        f"  'Besser als der Pool' ist keine Abnahmebedingung -- ein kleinerer\n"
        f"  Verlust ist kein Gewinn, und genau das haelt `ratchet.py::decide` fest.\n"
        f"\n  Und was auch bei bestandener Abnahme noch fehlte: diese Kandidaten\n"
        f"  haben nie um einen Platz konkurriert. Ein ausgelassener Trade\n"
        f"  veraendert spaetere freie Slots, und das sieht nur ein vollstaendiger\n"
        f"  kausaler Portfolio-Replay. Die Signalstudie allein ist kein Urteil."
    )
    print("-" * 94)
    return 0


def run_arms(
    cases: list[Case],
    train: list[Case],
    develop: list[Case],
    confirm: list[Case],
    names: list[str],
    *,
    signature: str,
    corrected: float,
) -> list[ArmResult]:
    """Die fuenf vorab angemeldeten Arme, jeder mit eingefrorenen
    Out-of-Sample-Predictions.

    Die Reihenfolge ist die der Registrierung und nicht verhandelbar:
    zwei Basislinien, eine Zufallskontrolle, dann die beiden Modelle.
    """
    rng = np.random.default_rng(SEED)
    results: list[ArmResult] = []
    vintage = case_vintage(cases)
    print(f"Datenstand der Faelle: {vintage[:16]}\n")
    print("  Eingefrorene Out-of-Sample-Predictions:")

    # E1.1 und E1.2: die beiden Basislinien, ohne Modell.
    results.append(evaluate("E1.1 ungefilterter Pool", confirm, of=len(confirm), level=corrected))
    freeze_arm(
        "E1.1 ungefilterter Pool",
        confirm,
        [True] * len(confirm),
        scores=None,
        signature=signature,
        vintage=vintage,
    )

    taken = [c for c in confirm if c.refused_by is None]
    results.append(evaluate("E1.2 heutiger Risikofilter", taken, of=len(confirm), level=corrected))
    freeze_arm(
        "E1.2 heutiger Risikofilter",
        confirm,
        [c.refused_by is None for c in confirm],
        scores=None,
        signature=signature,
        vintage=vintage,
    )

    # E1.3: Zufallsfilter gleicher Selektivitaet wie die Modellarme.
    mask = rng.random(len(confirm)) < KEEP_SHARE
    results.append(
        evaluate(
            "E1.3 Zufallsfilter (Kontrolle)",
            [c for c, keep in zip(confirm, mask, strict=True) if keep],
            of=len(confirm),
            level=corrected,
        )
    )
    freeze_arm(
        "E1.3 Zufallsfilter (Kontrolle)",
        confirm,
        [bool(k) for k in mask],
        scores=None,
        signature=signature,
        vintage=vintage,
    )

    # E1.4: logistische Regression. Schwelle im ENTWICKLUNGSfenster gewaehlt
    # und eingefroren, nie im Bestaetigungsfenster.
    packed = fit_logistic(train, names)
    threshold = float(np.quantile(score_logistic(develop, names, packed), 1.0 - KEEP_SHARE))
    scores = score_logistic(confirm, names, packed)
    results.append(
        evaluate(
            "E1.4 logistische Regression",
            [c for c, s in zip(confirm, scores, strict=True) if s >= threshold],
            of=len(confirm),
            level=corrected,
        )
    )
    freeze_arm(
        "E1.4 logistische Regression",
        confirm,
        [bool(s >= threshold) for s in scores],
        scores=scores,
        signature=signature,
        vintage=vintage,
    )

    # E1.5: flaches LightGBM, Komplexitaet in EXPERIMENTS_NEXT.yaml vorab
    # fixiert. Schwelle wieder aus dem Entwicklungsfenster, nie aus dem
    # Bestaetigungsfenster.
    if lgb is None:
        print("  (LightGBM nicht verfuegbar -- E1.5 als nicht testbar registriert)")
    else:
        model = lgb.LGBMRegressor(**LGBM_FIXED)
        model.fit(matrix(train, names), [c.net_r for c in train])
        dev_scores = model.predict(matrix(develop, names))
        gate = float(np.quantile(dev_scores, 1.0 - KEEP_SHARE))
        tree_scores = model.predict(matrix(confirm, names))
        results.append(
            evaluate(
                "E1.5 flaches LightGBM",
                [c for c, s in zip(confirm, tree_scores, strict=True) if s >= gate],
                of=len(confirm),
                level=corrected,
            )
        )
        freeze_arm(
            "E1.5 flaches LightGBM",
            confirm,
            [bool(s >= gate) for s in tree_scores],
            scores=tree_scores,
            signature=signature,
            vintage=vintage,
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="")
    args = parser.parse_args()

    config = load_config()
    # Die kanonische Signatur, nicht nachgebaut: die 12.843 Zeilen im Ledger
    # sind byteweise auf sie geschluesselt, und eine zweite Schreibweise
    # waere eine zweite Population.
    signature = run_signature(config)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or list(
        config.engine.symbols.active
    )

    print("=" * 94)
    print("E1 -- Meta-Labeling: erkennen Merkmale vom Entscheidungszeitpunkt die Gewinner?")
    print("=" * 94)
    print(f"\nSignatur: {signature}\n")

    cases = build_cases(symbols, signature=signature)
    if len(cases) < MIN_CASES:
        raise SystemExit(f"Nur {len(cases)} aufgeloeste Kandidaten -- zu wenig fuer drei Fenster.")

    train, develop, confirm = split(cases)
    names = sorted(cases[0].features)
    corrected = 1.0 - 0.05 / TOTAL_COMPARISONS

    print(
        f"\nKandidaten gesamt {len(cases):,}  "
        f"(genommen {sum(1 for c in cases if c.refused_by is None):,}, "
        f"abgelehnt {sum(1 for c in cases if c.refused_by):,})"
    )
    print(
        f"Fenster: trainieren {len(train):,} | entwickeln {len(develop):,} | "
        f"bestaetigen {len(confirm):,}   (Purge {PURGE_MS // HOUR_MS}h zwischen allen)"
    )
    print(f"Korrigiertes Niveau bei {TOTAL_COMPARISONS} Vergleichen: {100 * corrected:.3f}%")
    # Die Population, in einem Satz, im Kopf des Berichts.
    #
    # Ohne diese Zeile sahen zwei Studien mit VERSCHIEDENEN Populationen gleich
    # aus: `study_exits` filtert vier Ablehnungsgruende weg, diese hier zwei,
    # und der Unterschied war nur aus zwei Quelldateien zu erschliessen.
    print(f"{SAFETY_NOTE}\n")

    if not confirm:
        raise SystemExit("Leeres Bestaetigungsfenster -- mehr Zeit oder mehr Maerkte noetig.")

    results = run_arms(
        cases, train, develop, confirm, names, signature=signature, corrected=corrected
    )

    print(f"  {'Arm':30s} {'n':>6s} {'Anteil':>7s} {'Netto-R':>9s}  korrigiertes Intervall")
    print("  " + "-" * 88)
    for arm in results:
        if arm.n == 0:
            print(f"  {arm.name:30s} {'keine':>6s}")
            continue
        mark = " *" if arm.proven else ""
        print(
            f"  {arm.name:30s} {arm.n:>6d} {100 * arm.share:>6.1f}% "
            f"{arm.mean_net_r:>+9.4f}  [{arm.low:+.4f}, {arm.high:+.4f}]{mark}"
        )

    judge(results)


if __name__ == "__main__":
    raise SystemExit(main())
