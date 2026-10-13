"""Das Buch des gepoolten Kontos — und die vierte Grenze, die jetzt greift.

**Der Defekt.** `live/paper.py` baute `AccountState.from_history(...)` ohne
`open_positions`. `risk/limits.py:137` setzt dann `open_positions or []` ein,
und die beiden Zählprüfungen rechnen `0 >= 2` und `0 >= 1` — sie können
nicht auslösen. Drei der vier Kontogrenzen griffen, nicht vier, und die Zahl
„vier" stand in `config/risk.yaml`, also in genau der Datei, die am
13.10.2026 die zwölffache Positionsgröße begründete.

**Die Entscheidung, die man übersehen kann: ein arbeitender Auftrag belegt
einen Platz.** Der Deckel wird zur *Vorschlagszeit* geprüft, eine Position
entsteht zur *Füllzeit*. Zählte man nur gefüllte Positionen, könnten zwölf
Aufträge gleichzeitig arbeiten, alle zwölf füllen, und der Deckel hätte nie
etwas gesehen. `test_a_working_order_occupies_a_place` ist der Test, ohne
den die Reparatur nur so aussieht.

**Und die Gegenprobe:** ohne Buch verhält sich ein Händler wie vorher. Daran
hängen der Golden-Tape und `tests/test_papertrade.py`, und wenn sich das
ändert, ist es ein Befund und keine Nebenwirkung.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from tests.test_journal_history import SIG
from tests.test_journal_history import entry as journal_entry
from traidingbrain.clock import FixedClock
from traidingbrain.config.settings import AppConfig, SimulationConfig, load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import OrderType, Side
from traidingbrain.journal.signals import SignalStore
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.book import OpenBook
from traidingbrain.live.paper import PaperTrader
from traidingbrain.live.paperstate import PaperStateStore
from traidingbrain.risk.limits import KillSwitch, RiskLimits
from traidingbrain.sim.broker import PendingEntry, SimBroker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINUTE = 60_000
NOW = 1_700_000_000_000


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config(PROJECT_ROOT / "config")


def sim_config() -> SimulationConfig:
    return SimulationConfig.model_validate({
        "initial_equity": 10_000.0,
        "slippage_bps": 0.0,
        "fill_on_touch": True,
        "entry_expiry_bars": 8,
        "pessimistic_intrabar": True,
    })


def order(**overrides: object) -> PendingEntry:
    defaults: dict[str, object] = {
        "side": Side.LONG,
        "order_type": OrderType.LIMIT,
        "limit_price": 100.0,
        "stop": 98.0,
        "target": 106.0,
        "qty": 1.0,
        "leverage": 5.0,
        "created_ts": EPOCH,
        "expires_ts": EPOCH + 100 * MINUTE,
        "risk_amount": 10.0,
    }
    return PendingEntry(**(defaults | overrides))  # type: ignore[arg-type]


def desk(book: OpenBook, symbol: str) -> SimBroker:
    spec = make_symbol_spec(symbol=symbol, taker_fee=0.0, maker_fee=0.0)
    broker = SimBroker(spec, sim_config())
    book.attach(symbol, broker, spec)
    return broker


# --------------------------------------------------------------------------- #
# Was das Buch zeigt
# --------------------------------------------------------------------------- #


def test_an_empty_book_holds_nothing() -> None:
    book = OpenBook()
    desk(book, "BTCUSDT")
    desk(book, "ETHUSDT")

    assert len(book) == 2
    assert book.positions() == []


def test_a_filled_position_appears_with_its_symbol() -> None:
    book = OpenBook()
    broker = desk(book, "BTCUSDT")
    desk(book, "ETHUSDT")

    broker.submit(order())
    broker.on_minute(EPOCH, 100.5, 101.0, 99.5)
    assert broker.position is not None

    held = book.positions()
    assert [p.symbol for p in held] == ["BTCUSDT"]
    assert held[0].entry_price == pytest.approx(broker.position.entry_price)
    assert held[0].liquidation_price == pytest.approx(broker.position.liq_price)


def test_a_working_order_occupies_a_place() -> None:
    """Die Entscheidung, ohne die der Deckel nichts bewirkt.

    Geprueft wird zur Vorschlagszeit, gefuellt wird spaeter. Zaehlte das Buch
    nur gefuellte Positionen, koennten zwoelf Auftraege gleichzeitig
    arbeiten, alle zwoelf fuellen, und der Deckel haette nie etwas gesehen.
    """
    book = OpenBook()
    broker = desk(book, "SOLUSDT")

    assert broker.submit(order()) is True
    assert broker.position is None, "noch nicht gefuellt -- das ist der Punkt"

    held = book.positions()
    assert [p.symbol for p in held] == ["SOLUSDT"]
    assert held[0].entry_price == pytest.approx(100.0)
    assert held[0].liquidation_price > 0.0


def test_a_symbol_contributes_at_most_one_place() -> None:
    """`submit` lehnt ab, solange etwas laeuft -- also nie zwei je Symbol."""
    book = OpenBook()
    broker = desk(book, "BTCUSDT")
    broker.submit(order())
    broker.on_minute(EPOCH, 100.5, 101.0, 99.5)
    broker.submit(order(created_ts=EPOCH + MINUTE))

    assert len(book.positions()) == 1


def test_a_closed_position_frees_its_place() -> None:
    book = OpenBook()
    broker = desk(book, "BTCUSDT")
    broker.submit(order())
    broker.on_minute(EPOCH, 100.5, 101.0, 99.5)
    assert len(book.positions()) == 1

    broker.close_at(101.0, EPOCH + 5 * MINUTE)

    assert book.positions() == []


def test_an_expired_order_frees_its_place() -> None:
    """Ein Auftrag, der nie erreicht wurde, darf keinen Platz halten."""
    book = OpenBook()
    broker = desk(book, "BTCUSDT")
    broker.submit(order(expires_ts=EPOCH + 2 * MINUTE))
    broker.on_minute(EPOCH, 105.0, 106.0, 103.0)
    assert len(book.positions()) == 1

    broker.on_minute(EPOCH + 2 * MINUTE, 105.0, 106.0, 103.0)

    assert broker.expired_entries == 1
    assert book.positions() == []


# --------------------------------------------------------------------------- #
# Die Grenze am echten Objekt
# --------------------------------------------------------------------------- #


def trader_with_book(
    tmp_path: Path, config: AppConfig, *, book: OpenBook | None, cap: int
) -> PaperTrader:
    journal = JournalStore(tmp_path / "journal.sqlite")
    shipped = config.risk.limits.model_copy(update={"max_open_positions": cap})
    return PaperTrader(
        "BTCUSDT",
        config,
        source=None,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=PaperStateStore(tmp_path / "paper.sqlite"),
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(NOW),
        signals=SignalStore(tmp_path / "signals.sqlite"),
        run_signature=SIG,
        limits=RiskLimits(shipped, KillSwitch(tmp_path / "KILL_SWITCH")),
        book=book,
    )


def test_the_cap_blocks_once_the_account_is_full(tmp_path: Path, config: AppConfig) -> None:
    """Der Fall, den `config/risk.yaml` seit immer behauptet hat.

    Zwei fremde Symbole halten Plaetze, der dritte Haendler fragt, und der
    Deckel von zwei lehnt ab. Vor dem 13.10.2026 war das auf diesem Pfad
    unmoeglich: `open_positions` war immer leer.
    """
    book = OpenBook()
    for symbol in ("ETHUSDT", "SOLUSDT"):
        broker = desk(book, symbol)
        broker.submit(order())
        broker.on_minute(EPOCH, 100.5, 101.0, 99.5)
    assert len(book.positions()) == 2

    trader = trader_with_book(tmp_path, config, book=book, cap=2)
    blocked = trader._blocked_by_limits(NOW)

    assert blocked is not None
    assert "positions already open" in blocked
    assert "limit 2" in blocked


def test_the_cap_lets_the_account_fill_up_to_its_limit(
    tmp_path: Path, config: AppConfig
) -> None:
    book = OpenBook()
    broker = desk(book, "ETHUSDT")
    broker.submit(order())
    broker.on_minute(EPOCH, 100.5, 101.0, 99.5)

    trader = trader_with_book(tmp_path, config, book=book, cap=2)

    assert trader._blocked_by_limits(NOW) is None


def test_without_a_book_the_cap_cannot_fire(tmp_path: Path, config: AppConfig) -> None:
    """Der Defekt selbst, als festgehaltene Eigenschaft des buchlosen Pfads.

    Nicht, weil er erwuenscht ist, sondern weil der Golden-Tape und
    `test_papertrade.py` diesen Pfad fahren und sich nicht aendern duerfen.
    Faellt dieser Test, hat sich der Vorgabefall bewegt, und das waere ein
    Befund.
    """
    trader = trader_with_book(tmp_path, config, book=None, cap=1)

    assert trader._blocked_by_limits(NOW) is None


def test_a_foreign_symbols_place_does_not_trip_the_per_symbol_rule(
    tmp_path: Path, config: AppConfig
) -> None:
    """`max_positions_per_symbol` zaehlt nur das eigene Symbol.

    Sonst waere die Regel mit dem Buch von einer Symbolregel zu einer
    Kontoregel geworden, still und ohne dass jemand es entschieden hat.
    """
    book = OpenBook()
    broker = desk(book, "ETHUSDT")
    broker.submit(order())
    broker.on_minute(EPOCH, 100.5, 101.0, 99.5)

    trader = trader_with_book(tmp_path, config, book=book, cap=12)

    assert trader._blocked_by_limits(NOW) is None


def test_the_loss_streak_stays_a_symbol_question(
    tmp_path: Path, config: AppConfig
) -> None:
    """Die beiden Geltungsbereiche sind verschieden, und das mit Absicht.

    Positionen zaehlen ueber das Konto, Verlustserien ueber das Symbol. Hier
    wird festgehalten, dass das Buch die Verlustseite NICHT angefasst hat.
    """
    journal = JournalStore(tmp_path / "journal.sqlite")
    hour = 3_600_000
    journal.record([  # type: ignore[arg-type]
        journal_entry(f"live-ETHUSDT-{i}", symbol="ETHUSDT",
                      closed_ts=NOW - (3 - i) * hour, net_pnl=-10.0, run_signature=SIG)
        for i in range(3)
    ])
    shipped = config.risk.limits.model_copy(
        update={"cooldown_after_consecutive_losses": 3, "max_open_positions": 12}
    )
    trader = PaperTrader(
        "BTCUSDT",
        config,
        source=None,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=PaperStateStore(tmp_path / "paper.sqlite"),
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(NOW),
        signals=SignalStore(tmp_path / "signals.sqlite"),
        run_signature=SIG,
        limits=RiskLimits(shipped),
        book=OpenBook(),
    )

    assert trader._blocked_by_limits(NOW) is None, (
        "drei Verluste auf ETHUSDT sind keine Verlustserie von BTCUSDT"
    )


# --------------------------------------------------------------------------- #
# Der Waechter: gibt papertrade.py das Buch weiter?
# --------------------------------------------------------------------------- #


def papertrader_calls(path: Path) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PaperTrader"
    ]


def test_the_guard_below_can_find_a_call() -> None:
    """Zuerst der Waechter gegen sich selbst.

    Am 12.10.2026 war ein gleichartiger Waechter gruen, weil er NULL
    Aufrufstellen fand -- er haette auch bei geloeschtem Baum bestanden.
    """
    assert papertrader_calls(PROJECT_ROOT / "scripts" / "papertrade.py")


def test_the_paper_trader_is_handed_the_book() -> None:
    naked = [
        call.lineno
        for call in papertrader_calls(PROJECT_ROOT / "scripts" / "papertrade.py")
        if "book" not in {keyword.arg for keyword in call.keywords}
    ]

    assert not naked, (
        "PaperTrader ohne `book=` gebaut -- dann ist `open_positions` leer und "
        f"der Deckel auf offene Positionen kann nicht ausloesen: {naked}"
    )


def test_the_attach_loop_covers_every_trader() -> None:
    """Das Buch muss ALLE Haendler kennen, nicht den letzten.

    Ein `attach` ausserhalb der Schleife waere gruen in jedem Test mit einem
    Symbol und falsch im Betrieb mit zwoelf.
    """
    source = (PROJECT_ROOT / "scripts" / "papertrade.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    attaches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "attach"
    ]
    assert attaches, "kein attach-Aufruf gefunden -- Waechter blind"

    in_loop = []
    for loop in (n for n in ast.walk(tree) if isinstance(n, ast.For)):
        for inner in ast.walk(loop):
            if inner in attaches:
                in_loop.append(inner)
    assert len(in_loop) == len(attaches), (
        "ein attach-Aufruf steht nicht in einer Schleife -- dann kennt das "
        "Buch nur einen Teil der Haendler"
    )
