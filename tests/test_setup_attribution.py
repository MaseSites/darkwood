"""Welchem Setup ein Trade zugeschrieben wird — nur einem freigegebenen.

**Der Defekt, gefunden am 14.10.2026.** `journal/build.py:_setup_for` fragte
`evaluate_all`, und das läuft über `TRADEABLE` — also über *alle* Setups,
auch die, die die Konfiguration abgeschaltet hat. `GuidePool.propose_at`
läuft dagegen nur über die freigegebenen. C steht an Stelle 2 von sechs, vor
E, F und G; ein Trade, den E, F oder G erzeugt hat, bekam darum das Etikett
„C", sobald C auf demselben Balken mitfeuerte.

Gemessen in `data/replay_fills/` — 7.335 Trades über zwölf Märkte, gerechnet
unter `enabled: [A, B, E, F, G]`:

    204 Trades (2.8 %) tragen `setup_key = "C"`,
    und C war während des ganzen Laufs ausgeschaltet.

Damit ist jede Zahl je Setup für E, F und G zu klein und in ihrer
Zusammensetzung falsch — E hatte 168 Zeilen, F hatte 25.

Nachgeprüft wurde die Reparatur an echten Kerzen, nicht an der Zusicherung:
die beiden ETHUSDT-Trades mit Etikett C lösen sich zu **G** und **E** auf,
also genau zu Setups, die in der Reihenfolge nach C kommen.

**Warum der Golden-Test das nicht fand.** Er lief grün, vor und nach der
Reparatur. Auf seinem gefrorenen Band feuert C offenbar nie neben E, F oder
G — der Pfad existiert dort nicht. Ein grüner Test ist kein Beweis für eine
Eigenschaft, die seine Daten nicht hergeben.

**Die Konstruktion hier ist deshalb unterscheidend statt zufällig.** Nur `G`
wird freigegeben, also das LETZTE Setup der Reihenfolge. Unter der alten
Fassung hätte jeder Treffer von A, B, C, E oder F gewonnen; unter der neuen
darf nur `G` herauskommen. Dazu ein Boden: feuert gar nichts, sagt der Test
nichts, und das muss er selbst merken.
"""

from __future__ import annotations

import pytest

from tests.factories import make_symbol_spec  # noqa: F401  (Parität mit den anderen Dateien)
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.journal.build import _setup_for
from traidingbrain.strategy.setups import TRADEABLE, evaluate_all

PROJECT_CONFIG = load_config()

#: Das letzte Setup in `TRADEABLE`. Genau darum geht es: ein Filter, der nur
#: das letzte durchlässt, ist der strengste Test für eine Reihenfolge-Falle.
#: `Setup.key` ist das Etikett der Regel, `SetupSignal.setup` das desselben
#: Etiketts auf einem Treffer. Zwei Namen fuer dieselbe Sache, und sie zu
#: verwechseln kostete beim Schreiben dieses Tests einen Durchlauf.
LAST_KEY = TRADEABLE[-1].key

#: Wie viele Kerzen je Ebene. Die hoeheren Ebenen brauchen weniger, weil sie
#: denselben Zeitraum mit groesseren Kerzen abdecken -- und `MultiFrameAnalysis`
#: verlangt, dass der Zeitraum sich ueberlappt.
TAIL_BARS = {
    Timeframe.W1: 120,
    Timeframe.D1: 400,
    Timeframe.H4: 2_400,
    Timeframe.H1: 9_600,
    Timeframe.M15: 38_400,
}


def with_enabled(config: AppConfig, keys: list[str]) -> AppConfig:
    setups = config.engine.setups.model_copy(update={"enabled": keys})
    engine = config.engine.model_copy(update={"setups": setups})
    return config.model_copy(update={"engine": engine})


@pytest.fixture(scope="module")
def frames() -> dict[Timeframe, object]:
    """Echte Kerzen eines Marktes, weil synthetische kaum Setups auslösen."""
    store = ParquetStore(PROJECT_CONFIG.engine.paths.parquet_dir)
    loaded = {
        tf: store.read("ETHUSDT", tf) for tf in PROJECT_CONFIG.engine.timeframes.context
    }
    if any(frame.empty for frame in loaded.values()):
        pytest.skip("keine ETHUSDT-Kerzen -- scripts/backfill.py zuerst")
    # Nur das Ende der Historie.
    #
    # Die ganze Analyse zu bauen dauert rund 100 Sekunden, und ein Test, der
    # die Suite um zwei Minuten verlaengert, wird irgendwann uebersprungen --
    # dann prueft er nichts mehr. Der Ausschnitt muss nur gross genug sein,
    # dass Setups darin feuern, und der Boden unten merkt, wenn nicht.
    return {tf: frame.tail(TAIL_BARS[tf]).reset_index(drop=True)
            for tf, frame in loaded.items()}


def test_only_an_enabled_setup_is_ever_attributed(frames: dict) -> None:
    """Nur `G` freigegeben, also darf nur `G` herauskommen.

    Der Boden steht in der zweiten Zusicherung: ohne einen einzigen Treffer
    wäre die erste trivial wahr, und das ist genau die Form von grünem Test,
    die diesen Defekt ein Jahr lang hätte überdauern können.
    """
    config = with_enabled(PROJECT_CONFIG, [LAST_KEY])
    analysis = MultiFrameAnalysis(frames, config.engine)

    total = len(analysis.signal)
    step = max(1, total // 400)
    found: list[str] = []
    for index in range(total - 1, 0, -step):
        for side in (Side.LONG, Side.SHORT):
            signal = _setup_for(analysis, index, side)
            if signal is not None:
                found.append(signal.setup)

    assert all(key == LAST_KEY for key in found), (
        f"zugeschrieben wurde {sorted(set(found))}, freigegeben ist nur "
        f"[{LAST_KEY}] -- ein abgeschaltetes Setup kann keinen Trade erzeugt "
        "haben, also darf es auch keinen tragen"
    )
    assert found, (
        "kein einziges Setup hat auf diesem Band gefeuert. Dann sagt die "
        "Zusicherung darueber nichts, und der Test ist eine Attrappe."
    )


def test_evaluate_all_still_returns_every_setup(frames: dict) -> None:
    """Die Gegenprobe: `evaluate_all` darf NICHT filtern.

    Die Reparatur gehört in `_setup_for`, nicht in `evaluate_all` -- letzteres
    beantwortet die Frage „was hat auf diesem Balken gefeuert" und wird von
    Studien gebraucht, die gerade wissen wollen, was ein abgeschaltetes Setup
    getan hätte. Wer den Filter eine Ebene tiefer schiebt, nimmt ihnen die
    Frage weg, und zwar unbemerkt.
    """
    analysis = MultiFrameAnalysis(frames, PROJECT_CONFIG.engine)
    keys = {setup.key for setup in TRADEABLE}

    seen: set[str] = set()
    total = len(analysis.signal)
    for index in range(total - 1, max(0, total - 1500), -7):
        frame = analysis.analyses[PROJECT_CONFIG.engine.timeframes.signal]
        at = analysis.aligned_indices(index)
        if at is None:
            continue
        position = at.get(PROJECT_CONFIG.engine.timeframes.signal)
        if position is None:
            continue
        seen.update(signal.setup for signal in evaluate_all(frame, position))
        if len(seen) > 1:
            break

    assert seen, "evaluate_all hat auf diesem Abschnitt nichts gefunden"
    assert seen <= keys
