"""Der Live-Entscheidungspfad, eingefroren — damit eine Verhaltensänderung auffällt.

**Warum dieser Test existiert.** Am 09.10.2026 musste die Vorwärtsstichprobe
dreimal nachgeschnitten werden (18 → 14 → 11 Trades), und zweimal war die
Begründung falsch: die Commits waren danach ausgewählt, *wie strategiewirksam
ihr Titel klingt*. Die echte Grenze trug einen Buchhaltungstitel („Stop losing
forward evidence while it is being recorded", `MAX_DECISION_ATTEMPTS = 3`) und
wurde erst vier Tage später aus neunzehn Diffs rekonstruiert.

Nötig war das, weil der Replay-Pfad einen Golden-Test hat
(`tests/golden/backtest_baseline.json`, Fills und Kapitalkurve) und der
**Papierhandel keinen** — obwohl er der Pfad ist, der die einzige noch
wachsende Evidenz erzeugt. Dieser Test schliesst die Lücke: er hätte
`MAX_DECISION_ATTEMPTS` am Tag seines Entstehens gemeldet.

**Was er abdeckt.** Die ganze Kette, die entscheidet, *welche Trades
entstehen*: die Analyse-Pipeline (Indikatoren, Struktur, Liquidität, Regime),
die Setups, die Bewertung über `reason_at`, und die Risikoschicht mit
Ablehnungsregeln, Sizing und Hebel. Nicht abgedeckt: Fills und Ausstiege — die
hat der Replay-Golden-Test, und `sim/broker.py` ist beiden gemeinsam.

**Warum er durch den echten `PaperTrader` fährt und nicht durch eine Kopie
von `_maybe_open`.** Eine Kopie kann abdriften. Driftet sie, bleibt der Test
grün, während sich das Live-Verhalten ändert — genau der Fehler, den er
verhindern soll. Gehasht wird deshalb, was der **Live-Code selbst** in den
`SignalStore` schreibt.

**Warum er nicht leer bestehen kann.** Die bestehenden Papierhandels-Tests
nehmen `FixedIntent` statt der echten Strategie, mit Begründung im Modul:
*„a real setup fires on a handful of bars in a fixture and on none in some."*
Feuert die echte Strategie auf der Fixture nie, ist der Hash über eine leere
Folge stabil, egal was sich ändert. Darum behauptet dieser Test seine eigenen
Untergrenzen mit — Zahl der Signale, der angenommenen, der abgelehnten je
Regel, der verschiedenen Setups — und fällt, wenn die Folge dünn wird.

Reproduktion des Bandes:

    python scripts/freeze_decision_tape.py

Golden-Datei neu schreiben, absichtlich:

    UPDATE_GOLDEN=1 pytest tests/test_live_decision_golden.py
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tests.factories import make_symbol_spec
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.clock import FixedClock
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.frames import frame_to_bars, timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import Bar, FundingRate, SymbolSpec
from traidingbrain.journal.build import reason_at
from traidingbrain.journal.record import Source
from traidingbrain.journal.signals import Action, SignalStore
from traidingbrain.journal.store import JournalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.live.paper import PaperTrader
from traidingbrain.live.paperstate import PaperStateStore
from traidingbrain.sim.plan import assess, setup_label
from traidingbrain.strategies.guide import GuidePool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAPE = PROJECT_ROOT / "tests" / "golden" / "decision_tape"

#: Die Märkte aus dem Band. BTC deckt die Kostenregel, DOT den angenommenen
#: Pfad und die Chance-Risiko-Regel. Begründung mit Messtabelle in
#: `scripts/freeze_decision_tape.py`.
SYMBOLS = ("BTCUSDT", "DOTUSDT")

#: Wie viele Signalbalken der **echte Händler** durchläuft. Jeder Balken, an dem
#: das Konto flach ist, kostet einen vollständigen Aufbau der Analyse (gemessen
#: 1,68 s bei 800 Balken je Ebene), also ist das die bindende Grösse für die
#: Laufzeit. 40 reicht, weil das Band gezielt 31 Balken nach den beiden echten
#: Live-Entscheidungen endet — sie liegen damit im Fenster.
STEPS = 40

#: Fenster des **breiten** Tests, der ohne Broker läuft und darum nur einen
#: Aufbau je Markt braucht.
SWEEP = 700

#: Untergrenzen, die verhindern, dass ein Test leer besteht. Sie stehen
#: *unterhalb* des gemessenen Standes, damit normale Streuung sie nicht
#: auslöst, aber weit über null. Gemessene Werte stehen in der Golden-Datei.
FLOOR_SIGNALS = 3
FLOOR_TAKEN = 1
FLOOR_SETUPS = 2
FLOOR_SWEEP_DECISIONS = 60
FLOOR_SWEEP_TAKEN = 8
FLOOR_SWEEP_RULES = 2

#: Das Eigenkapital, auf dem gerechnet wird. EIN Wert, und das ist gemessen:
#: bei 1 000, 5 000, 12 000 und 50 000 USDT sind Vorschlaege, Annahmen und
#: Ablehnungen identisch, weil die Kostenregel Maut mit riskiertem Betrag
#: vergleicht und beide mit dem Konto skalieren. Zwei Niveaus waeren derselbe
#: Hash zweimal.
EQUITY = 1000.0

#: Felder, die NICHT in den Hash gehen, mit Grund.
#:
#: `code_version` stempelt der Speicher je Zeile mit dem aktuellen Commit. Im
#: Hash würde der Test bei jedem Commit brechen, auch bei einem, der nur einen
#: Bericht schreibt — die Signatur wäre dann zu *fein*, genau die andere Hälfte
#: des Problems vom 09.10. `run_signature` bleibt drin: sie deckt die
#: Konfiguration, und eine Konfigurationsänderung SOLL diesen Test brechen.
UNHASHED = ("code_version",)


class FrozenTape:
    """Serviert das eingefrorene Band bis zu einem wandernden Schnitt.

    Der Schnitt ist der Punkt: ein Vorwärtshändler darf nur geschlossene
    Balken bis *jetzt* sehen. Eine Quelle, die die ganze Reihe herausgibt,
    liesse jeden Test hier die Zukunft lesen und bestehen.
    """

    def __init__(self, bars: dict[Timeframe, list[Bar]], now_ms: int) -> None:
        self.bars = bars
        self.now_ms = now_ms
        self.calls = 0

    def fetch_ohlcv(
        self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int
    ) -> list[Bar]:
        self.calls += 1
        step = timeframe_ms(timeframe)
        window = [
            bar
            for bar in self.bars.get(timeframe, [])
            if since_ms <= bar.ts and bar.ts + step <= self.now_ms
        ]
        return window[:limit]

    def fetch_funding(
        self, symbol: str, since_ms: int, limit: int = 200
    ) -> list[FundingRate]:
        return []

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec:
        return make_symbol_spec()


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config(PROJECT_ROOT / "config")


@pytest.fixture(scope="module")
def tape(config: AppConfig) -> dict[str, dict[Timeframe, pd.DataFrame]]:
    """Das eingefrorene Band, aus `tests/golden/decision_tape`."""
    if not (TAPE / "MANIFEST.json").exists():
        pytest.fail(
            f"kein eingefrorenes Band unter {TAPE.relative_to(PROJECT_ROOT)}. "
            "Erzeugen mit: python scripts/freeze_decision_tape.py"
        )
    store = ParquetStore(TAPE)
    frames: dict[str, dict[Timeframe, pd.DataFrame]] = {}
    for symbol in SYMBOLS:
        frames[symbol] = {}
        for timeframe in config.engine.timeframes.context:
            frame = store.read(symbol, timeframe).reset_index(drop=True)
            assert not frame.empty, f"{symbol} {timeframe.value} leer im Band"
            frames[symbol][timeframe] = frame
    return frames


def _run_one(
    symbol: str,
    frames: dict[Timeframe, pd.DataFrame],
    config: AppConfig,
    workspace: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Den echten Papierhändler über das Band fahren und seine Signale einsammeln."""
    signal_tf = config.engine.timeframes.signal
    signal_ms = timeframe_ms(signal_tf)
    signal_frame = frames[signal_tf]

    # Der Händler SCHREIBT in den Speicher (`paper.py:295`), also nie in die
    # Fixture hinein: eine Kopie je Lauf, und das Band im Repo bleibt unberührt.
    store = ParquetStore(workspace / "ohlcv")
    cut_index = len(signal_frame) - STEPS
    assert cut_index > 0, "Band kürzer als das Fenster"
    cut_ts = int(signal_frame["ts"].iloc[cut_index])
    for timeframe, frame in frames.items():
        closed = frame[frame["ts"] + timeframe_ms(timeframe) <= cut_ts]
        if not closed.empty:
            store.write(symbol, timeframe, closed)

    source = FrozenTape(
        {tf: frame_to_bars(frame) for tf, frame in frames.items()}, cut_ts
    )
    signals = SignalStore(workspace / "signals.sqlite")
    trader = PaperTrader(
        symbol,
        config,
        source=source,
        store=store,
        state=PaperStateStore(workspace / "paper.sqlite"),
        journal=JournalStore(workspace / "journal.sqlite"),
        spec=make_symbol_spec(),
        clock=FixedClock(cut_ts),
        signals=signals,
        run_signature=run_signature(config),
    )

    for _ in range(STEPS):
        source.now_ms += signal_ms
        trader.clock = FixedClock(source.now_ms)
        trader.step()

    rows = [
        {
            field: _plain(getattr(record, field))
            for field in record.__dataclass_fields__
            if field not in UNHASHED
        }
        for record in signals.all(source=Source.LIVE)
    ]
    tally = trader.stats.tally
    counters = {
        "proposed": tally.proposed,
        "not_ready": tally.not_ready,
        "opened": tally.opened,
        "refused_by_risk": tally.refused_by_risk,
        "failures": tally.failures,
    }
    return rows, counters


def _plain(value: Any) -> Any:
    """Enums auf ihren Wert, Floats gerundet — ein Hash über rohe Floats wäre
    plattformabhängig und würde auf einer anderen Maschine grundlos brechen."""
    if hasattr(value, "value") and not isinstance(value, (int, float, str)):
        return value.value
    if isinstance(value, float):
        return round(value, 8)
    return value


def test_the_frozen_tape_is_the_one_the_golden_file_was_written_from() -> None:
    """Band und Entscheidung getrennt prüfen, sonst ist ein Bruch nicht lesbar.

    Ändert sich der **Bandhash**, hat jemand die Eingabe erneuert — dann ist
    ein geänderter Entscheidungshash erwartbar und sagt nichts über den Code.
    Ändert sich **nur** der Entscheidungshash, hat sich das Verhalten geändert.
    Genau diese Unterscheidung hat am 09.10. gefehlt.
    """
    manifest = json.loads((TAPE / "MANIFEST.json").read_text(encoding="utf-8"))
    per_file = {
        str(p.relative_to(TAPE)).replace("\\", "/"): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in sorted(TAPE.rglob("*.parquet"))
    }
    joined = "".join(f"{name}:{sha}" for name, sha in sorted(per_file.items()))
    actual = hashlib.sha256(joined.encode()).hexdigest()
    assert actual == manifest["bandhash"], (
        "Das eingefrorene Band stimmt nicht mit seinem Manifest überein. "
        "Entweder wurde eine Parquet-Datei angefasst, oder das Band wurde neu "
        "erzeugt ohne das Manifest zu schreiben. Neu einfrieren mit: "
        "python scripts/freeze_decision_tape.py"
    )


def test_the_live_decision_path_is_frozen(
    tmp_path: Path,
    config: AppConfig,
    tape: dict[str, dict[Timeframe, pd.DataFrame]],
    golden: Callable[[str, Any], None],
) -> None:
    """Welche Signale der echte Papierhändler auf diesem Band erwägt, genommen
    wie abgelehnt — und mit welchen Zahlen."""
    payload: dict[str, Any] = {"steps": STEPS, "symbols": list(SYMBOLS), "runs": {}}
    all_rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        workspace = tmp_path / symbol
        workspace.mkdir()
        rows, counters = _run_one(symbol, tape[symbol], config, workspace)
        payload["runs"][symbol] = {"counters": counters, "signals": rows}
        all_rows.extend(rows)

    # --- Die Untergrenzen. Ohne sie könnte der Test leer bestehen. ---------- #
    assert len(all_rows) >= FLOOR_SIGNALS, (
        f"nur {len(all_rows)} Signale über {STEPS} Balken auf {len(SYMBOLS)} Märkten. "
        "Ein Hash über eine so dünne Folge sagt nichts: er bliebe stabil, auch "
        "wenn sich die Strategie ändert. Entweder feuert die echte Strategie auf "
        "diesem Band nicht mehr -- das wäre selbst der Befund -- oder das Fenster "
        "ist zu klein. Gemessen beim Anlegen des Tests: siehe die Golden-Datei."
    )
    setups = {row["setup_key"] for row in all_rows}
    assert len(setups) >= FLOOR_SETUPS, (
        f"nur {len(setups)} verschiedene Setups ({sorted(setups)}). Eine Folge aus "
        "einem einzigen Setup deckt die Strategie nicht ab."
    )
    not_ready = sum(run["counters"]["not_ready"] for run in payload["runs"].values())
    assert not_ready == 0, (
        f"{not_ready} Balken meldeten not_ready, also war die Bewertung nicht "
        "aufgewärmt. Dann hasht dieser Test Aufwärmrauschen statt Entscheidungen. "
        "Das Band braucht mehr Balken je Ebene (scripts/freeze_decision_tape.py "
        "--bars)."
    )
    failures = sum(run["counters"]["failures"] for run in payload["runs"].values())
    assert failures == 0, (
        f"{failures} gescheiterte Zyklen auf einem eingefrorenen Band. Hier gibt es "
        "kein Netz, also ist das ein Fehler im Händler und nicht in der Leitung."
    )
    taken = [row for row in all_rows if row["action"] == Action.TAKEN.value]
    assert len(taken) >= FLOOR_TAKEN, (
        f"keine angenommene Entscheidung über {STEPS} Balken ({len(all_rows)} Signale, "
        "alle abgelehnt). Dann deckt dieser Test den Pfad nicht ab, auf dem Sizing und "
        "Hebel gerechnet werden. Das Band ist absichtlich so geschnitten, dass es die "
        "beiden echten Live-Entscheidungen vom 09.10. enthält -- wenn die hier nicht "
        "mehr entstehen, hat sich entweder das Band oder das Verhalten geändert."
    )

    golden("live_decisions", payload)


def test_every_decision_on_the_tape_is_frozen(
    config: AppConfig,
    tape: dict[str, dict[Timeframe, pd.DataFrame]],
    golden: Callable[[str, Any], None],
) -> None:
    """Jeder Balken, nicht nur die, an denen das Konto flach war.

    **Warum dieser Test neben dem anderen steht, und warum keiner allein
    genügt.** Der Händler erwägt ein Signal nur, wenn er flach ist — der
    „Belegungsschatten", der in diesem Projekt schon gemessen ist (4 090
    verdeckte Signale, 2,4-fach der sichtbaren). Über 40 Balken auf zwei
    Märkten liefert der echte Händler darum eine Handvoll Entscheidungen. Das
    genügt, um **Abdrift in der Orchestrierung** zu fangen, aber nicht, um eine
    Änderung an einem einzelnen Setup oder an einer Ablehnungsregel zuverlässig
    zu treffen.

    Dieser Test fährt dieselbe Kette über **jeden** Balken und braucht dafür
    nur einen Aufbau der Analyse je Markt. Er ruft dabei dieselben echten
    Bausteine auf, die `paper.py:_maybe_open` aufruft — `MultiFrameAnalysis`,
    `GuidePool.propose_at`, `reason_at`, `assess` — nicht eine Kopie ihrer
    Logik.

    **Seine Schwäche, ausdrücklich benannt:** er kennt die *Reihenfolge* der
    Kette aus `_maybe_open` und nicht aus dem Aufruf selbst. Ändert `paper.py`
    seine Kette, bleibt dieser Test grün. Genau dagegen steht
    `test_the_live_decision_path_is_frozen`, der durch den echten Händler
    fährt. Die beiden decken zusammen ab, was keiner einzeln kann: dieser die
    Bausteine in der Breite, jener die Orchestrierung.
    """
    signal_tf = config.engine.timeframes.signal
    signal_ms = timeframe_ms(signal_tf)
    expiry = config.engine.simulation.entry_expiry_bars
    pool = GuidePool.for_config(config)
    spec = make_symbol_spec()

    payload: dict[str, Any] = {"window": SWEEP, "runs": {}}
    decisions: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        frames = tape[symbol]
        analysis = MultiFrameAnalysis(frames, config.engine)
        frame = analysis.signal.frame
        total = len(frame)
        start = max(0, total - SWEEP)
        rows: list[dict[str, Any]] = []
        counters = {"proposed": 0, "incoherent": 0, "not_ready": 0}
        for index in range(start, total):
            intent = pool.propose_at(analysis, index)
            if intent is None:
                continue
            if not intent.is_coherent:
                counters["incoherent"] += 1
                continue
            counters["proposed"] += 1
            if reason_at(analysis, index, intent.side) is None:
                counters["not_ready"] += 1
                continue
            created = int(frame["ts"].iloc[index]) + signal_ms
            verdict = assess(
                intent,
                None,
                symbol=symbol,
                spec=spec,
                config=config,
                equity=EQUITY,
                created_ts=created,
                expires_ts=created + expiry * signal_ms,
            )
            rows.append({
                "index": index,
                "decided_ts": created,
                "setup": setup_label(intent),
                "side": _plain(intent.side),
                "entry": _plain(intent.entry),
                "stop": _plain(intent.stop),
                "target": _plain(intent.target),
                "accepted": verdict.accepted,
                "refused_by": _plain(verdict.refused_by) if verdict.refused_by else "",
                "reward_risk": _plain(verdict.reward_risk),
                "cost_fraction": _plain(verdict.cost_fraction),
                "risk_amount": _plain(verdict.risk_amount),
                "qty": _plain(verdict.qty),
                "leverage": _plain(verdict.leverage),
            })
        payload["runs"][symbol] = {"counters": counters, "decisions": rows}
        decisions.extend(rows)

    # --- Die Untergrenzen. Ohne sie könnte der Test leer bestehen. ---------- #
    assert len(decisions) >= FLOOR_SWEEP_DECISIONS, (
        f"nur {len(decisions)} Entscheidungen über {SWEEP} Balken auf "
        f"{len(SYMBOLS)} Märkten. Gemessen beim Anlegen waren es deutlich mehr; "
        "eine so dünne Folge hält keinen Hash, der etwas aussagt."
    )
    accepted = [row for row in decisions if row["accepted"]]
    assert len(accepted) >= FLOOR_SWEEP_TAKEN, (
        f"nur {len(accepted)} angenommene Entscheidungen. Sizing, Hebel und der "
        "Liquidationsabstand werden nur auf diesem Pfad gerechnet -- ohne ihn "
        "deckt der Hash die Risikoschicht nicht ab."
    )
    rules = {row["refused_by"] for row in decisions if row["refused_by"]}
    assert len(rules) >= FLOOR_SWEEP_RULES, (
        f"nur {sorted(rules)} als Ablehnungsgrund. Die Ablehnungsregeln sind die "
        "Hälfte der Frage, welche Trades entstehen."
    )
    setups = {row["setup"] for row in decisions}
    assert len(setups) >= FLOOR_SETUPS, (
        f"nur {len(setups)} verschiedene Setups ({sorted(setups)})."
    )
    not_ready = sum(run["counters"]["not_ready"] for run in payload["runs"].values())
    assert not_ready == 0, (
        f"{not_ready} Balken meldeten not_ready -- die Bewertung war nicht aufgewärmt, "
        "und dann hasht dieser Test Aufwärmrauschen. Mehr Balken je Ebene: "
        "scripts/freeze_decision_tape.py --bars"
    )

    golden("live_decisions_sweep", payload)
