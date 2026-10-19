"""Serve the confirmation dashboard.

    python scripts/run_dashboard.py             # nothing can reach an exchange
    python scripts/run_dashboard.py --demo      # with a sample proposal to look at
    python scripts/run_dashboard.py --execute   # a held confirmation reaches Bybit

Without `--execute` no executor is wired, so confirming a proposal reports what
would have been sent. That is the default, and it is what makes it safe to run
against real account data while the interface is still being shaped.

`--execute` arms the testnet executor, and arming it changes what two other
things have to be true. It needs credentials, and it needs a live price source --
because the drift check that refuses a stale proposal is the difference between
confirming a trade and confirming a trade that no longer exists at that price.
Both are required rather than optional, so there is no configuration in which the
dashboard can trade without being able to check the market first.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plantrade

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.api.app import Services, build_default_services, create_app
from traidingbrain.api.portfolio import account_equity
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.clock import SystemClock
from traidingbrain.config.settings import load_secrets
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.proposal import Position
from traidingbrain.execution.diagnose import diagnose
from traidingbrain.execution.intent import IntentLog
from traidingbrain.execution.order import BybitExecutor, UnsafeConfigurationError
from traidingbrain.execution.policy import policy_for
from traidingbrain.execution.venuebinding import (
    Environment,
    IncoherentVenueError,
    MainnetNotApprovedError,
    VenueBinding,
)
from traidingbrain.journal.history import closed_trades
from traidingbrain.journal.store import JournalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.live.paperstate import PaperStateStore
from traidingbrain.proposals.builder import BuildFailure
from traidingbrain.risk.limits import AccountState

DEMO_SPEC = {
    "price_tick": 0.1,
    "qty_step": 0.001,
    "min_qty": 0.001,
    "min_notional": 5.0,
    "max_leverage": 100.0,
    "taker_fee": 0.00055,
    "maker_fee": 0.0002,
    "maintenance_margin_rate": 0.005,
}


#: The port to serve on when nothing says otherwise.
#:
#: Read from the environment first, because a launcher that assigns ports needs a
#: way to tell the process which one it got. Nothing here depends on a particular
#: number -- there are no OAuth callbacks and no webhooks pointing at it -- so a
#: hardcoded port only ever means a collision with whatever else is already on it.
DEFAULT_PORT = int(os.environ.get("PORT") or 8787)

#: Die Konten, die dieses Dashboard zeigen kann.
#:
#: Je Konto drei Dinge, und alle drei muessen zusammenpassen, sonst zeigt
#: die Seite den Kontostand des einen mit den Trades des anderen:
#: der Speicher, der Signaturzusatz (welche Journalzeilen dazugehoeren) und
#: ein eigener Vorgabeport, damit zwei Fenster nebeneinander laufen koennen.
KONTEN: dict[str, tuple[str, str, str, int, float | None]] = {
    # Name: (Speicherdatei, Signaturzusatz, Kopfzeilen-Etikett, Vorgabeport)
    # Name: (Speicher, Signaturzusatz, Etikett, Port, Einsatz)
    #
    # Der Einsatz ist bei "live" None, weil er sich herleiten laesst: das
    # Konto entstand aus zwoelf Einzelkonten zu je 1.000. Das Plankonto ist
    # von Anfang an EINE Kasse mit 1.000 -- ohne die Angabe meldete das
    # Dashboard -91,67 %, weil es 12.000 als Einsatz annahm.
    "live": ("paper.sqlite", "", "", DEFAULT_PORT, None),
    "plan": ("plan_paper.sqlite", "plan30x7", "Plankonto 30%x7", DEFAULT_PORT + 1, 1_000.0),
}

#: Die VORWAERTSREGEL je Konto, oder None.
#:
#: Aus `plantrade.py` importiert statt hier wiederholt. Stuenden die Zahlen an
#: zwei Stellen, wuerde das Dashboard irgendwann eine Aussicht fuer eine
#: Groessenregel zeigen, die der Haendler gar nicht fuehrt -- derselbe Fehler,
#: den `_signatur()` weiter unten fuer die Laufsignatur beschreibt.
#:
#: `None` heisst: dieses Konto bemisst RUECKWAERTS (Risikobudget hinein, Menge
#: heraus). Dort gibt es kein `Anteil mal Hebel`, also auch keine Aussicht.
PLAN_SIZING: dict[str, tuple[float, float] | None] = {
    "live": None,
    "plan": (plantrade.MARGIN_ANTEIL, plantrade.HEBEL),
}

#: How far back --demo may look for a bar the analysis actually liked. Most bars
#: are declined, which is the system working; a demo that only tries the newest
#: one therefore shows an empty screen most of the time and reads as a failure.
DEMO_SEARCH_BARS = 3000


def seed_demo(services: Services) -> int:
    """Put real proposals on the screen, built by the real pipeline.

    Built rather than hand-written, so what is displayed is genuinely what the
    system produces -- a mocked-up ticket would hide exactly the formatting and
    rounding problems this is meant to surface.

    It searches backwards instead of asking about the newest bar only. Declining
    is the normal answer on any given bar, so asking once and reporting "declined"
    produced an empty dashboard with no visible reason, which is indistinguishable
    from something being broken.
    """
    config = services.config
    store = ParquetStore(config.engine.paths.parquet_dir)
    symbol = config.engine.symbols.active[0]
    frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
    if any(frame.empty for frame in frames.values()):
        print(f"  no market data for {symbol}; the dashboard will start empty")
        print(f"  fix with: python scripts/backfill.py {symbol} --since 2023-01-01")
        return 0

    analysis = MultiFrameAnalysis(frames, config.engine)
    builder = SnapshotBuilder(symbol, analysis, config.engine)
    brain = FakeBrain(config)
    spec = SymbolSpec(symbol=symbol, **DEMO_SPEC)
    services.specs[symbol] = spec

    last = len(analysis.signal) - 1
    examined = 0
    declined: dict[str, int] = {}
    for index in range(last, max(last - DEMO_SEARCH_BARS, 0), -1):
        snapshot = builder.build(index)
        if snapshot is None:
            continue
        examined += 1
        built = services.builder.build(
            brain.decide(snapshot), snapshot, spec, services.account_state()
        )
        if isinstance(built, BuildFailure):
            declined[str(built)] = declined.get(str(built), 0) + 1
            continue
        services.store.put(built)
        print(f"  seeded {built.side.value} {symbol} at {built.entry:,.2f}")
        return 1

    print(f"  no proposal in the last {examined:,} analysable bars. Most common reasons:")
    for reason, count in sorted(declined.items(), key=lambda item: -item[1])[:3]:
        print(f"    {count:>5,}x  {reason}")
    return 0


def _arm(services: Services) -> bool:
    """Connect the executor and the price source, or explain why not.

    Returns False rather than continuing unarmed. Starting up in a weaker mode
    than the one that was asked for is how someone ends up believing a
    confirmation reached the exchange when it did not.
    """
    # ERST die Bindung, DANN die Schluessel.
    #
    # Reihenfolge mit Absicht: passen die Boersen nicht zusammen, ist das keine
    # Frage der Zugangsdaten, und eine Meldung ueber fehlende Schluessel wuerde
    # den eigentlichen Grund verdecken.
    #
    # Mit den heutigen Daten BRICHT das hier ab, und das ist der Zweck: alle
    # Kerzen kommen von Binance (config/settings.yaml), ausfuehrbar ist nur
    # Bybit (es gibt nur BybitCredentials). Vorher lief genau diese Lage
    # stillschweigend -- Binance-Kerzen, Binance-Driftpruefung,
    # Bybit-Instrumentregeln, Bybit-Order. Siehe audit/P0A_LEGACY_FREEZE.md.
    config = services.config
    try:
        binding = VenueBinding.executable(
            data_venue=config.engine.exchange.name,
            price_venue=config.engine.exchange.name,
            # Die Preisprobe gehoert auf das MAINNET, auch wenn die Order ins
            # Testnet geht: sie soll gegen den Markt pruefen, den es gibt.
            # Vorher stand hier `testnet=secrets.bybit.testnet` -- die
            # Ausfuehrungsumgebung einer anderen Boerse.
            price_environment=Environment.MAINNET,
            instrument_spec_venue="bybit",
            execution_venue="bybit",
            execution_environment=(
                Environment.TESTNET if load_secrets().bybit.testnet
                else Environment.MAINNET
            ),
            policy=policy_for("bybit", "safety-first"),
        )
    except (IncoherentVenueError, MainnetNotApprovedError) as exc:
        print(f"\n  refusing to arm: {exc}\n", file=sys.stderr)
        print(
            "  Das Dashboard laeuft ohne --execute weiter und zeigt Vorschlaege.\n",
            file=sys.stderr,
        )
        return False
    services.binding = binding
    print(f"  binding: {binding.fingerprint()}")

    secrets = load_secrets()
    if not secrets.bybit.is_configured:
        print(
            "  --execute needs TB_BYBIT__API_KEY and TB_BYBIT__API_SECRET in .env "
            "(testnet keys from testnet.bybit.com)",
            file=sys.stderr,
        )
        return False

    try:
        executor = BybitExecutor(
            secrets.bybit.api_key.get_secret_value(),
            secrets.bybit.api_secret.get_secret_value(),
            IntentLog(config.engine.paths.data_dir / "intents.sqlite"),
            services.kill_switch,
            testnet=secrets.bybit.testnet,
            # Ausdruecklich, nicht aus einem Vorgabewert. Die Boerse der
            # Zugangsdaten ist Bybit (Secrets.bybit), also ist sie auch die
            # Boerse der Ausfuehrung -- und `BybitExecutor` lehnt jede andere ab.
            venue_name="bybit",
        )
        print(f"  preflight: {executor.preflight().describe()}")
    except UnsafeConfigurationError as exc:
        print(f"  refusing to arm: {exc}", file=sys.stderr)
        return False
    except Exception as exc:
        # A rejected key is a setup problem, and a traceback is indistinguishable
        # from a crash. The dashboard still runs; it just cannot trade.
        print("\n  Could not arm the executor.\n", file=sys.stderr)
        print(diagnose(exc, testnet=secrets.bybit.testnet).render(), file=sys.stderr)
        print(
            "\n  Everything except sending orders works without this: drop --execute\n"
            "  and the dashboard will show proposals and report what confirming\n"
            "  would have sent.\n",
            file=sys.stderr,
        )
        return False

    services.executor = executor
    # Read-only and credential-free: the price this checks against must come from
    # the public market, not from the account that is about to trade.
    # `testnet=False`, weil die Preisprobe gegen den echten Markt gehoert --
    # dieselbe Begruendung, die run_live.py:92 schon gibt ("Prices come from
    # mainnet"). Vorher stand hier `secrets.bybit.testnet`, also die
    # Ausfuehrungsumgebung einer ANDEREN Boerse: mit testnet=true und
    # venue=binance leitet venue.build auf demo-dapi.binance.com, und die
    # Driftpruefung verglich gegen Demo-Preise.
    services.prices = MarketData(
        venue_name=binding.price_venue,
        testnet=binding.price_environment is Environment.TESTNET,
        rate_limit_ms=config.engine.exchange.rate_limit_ms,
    )
    for symbol in config.engine.symbols.active:
        try:
            services.specs[symbol] = executor.symbol_spec(symbol)
        except Exception as exc:  # one bad symbol must not stop the others
            print(f"  no instrument rules for {symbol}: {exc}", file=sys.stderr)
    return True


def _free_port(host: str, preferred: int) -> int:
    """The preferred port, or the next free one.

    A second dashboard on a taken port fails with winerror 10048 and a sentence
    of Windows socket prose -- which reads like a broken program rather than
    "something is already listening there". Nothing here needs a particular
    number: no OAuth callback and no webhook points at it, so moving aside is
    strictly better than refusing to start.

    The banner says which port was used, because a dashboard on a port nobody
    was told about is the same as no dashboard.
    """
    for candidate in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return candidate
    # Zero asks the OS for any free port. Reaching here means twenty in a row
    # were taken, which is worth not failing over.
    return 0


def _signatur(services: Services) -> str:
    """Die Laufsignatur DIESES Kontos, mit Zusatz.

    Genau dieselbe Zusammensetzung wie in `scripts/papertrade.py`. Stimmten die
    beiden nicht ueberein, wuerde das Dashboard die Trades seines eigenen
    Kontos nicht finden und still mit einer leeren Historie rechnen -- also mit
    Verlustsicherungen, die nichts sehen.
    """
    basis = run_signature(services.config)
    return f"{basis}|{services.signature_suffix}" if services.signature_suffix else basis


def kontostand(services: Services) -> float:
    """Was DIESES Konto gerade haelt -- aus dem Kontospeicher.

    **Hier stand `config.engine.simulation.initial_equity`**, der Startwert
    EINES Marktes. Die drei Verlustsicherungen sind Prozente vom Konto, also
    rechnete das bestehende Konto gegen 1.000 statt gegen 11.775: der
    Tagesdeckel lag bei 54 statt bei rund 589, elffach zu eng, und das
    Dashboard meldete dauerhaft "blockiert".

    Sichtbar wurde es erst, als `/api/state` ueberhaupt ein Urteil zu sehen
    bekam. Vorher las der Endpunkt `services.account` -- immer `None` -- und
    meldete "kein Kontostand". Ein Fehler hielt den anderen verdeckt.

    `account_equity` ist die eine Stelle, die diese Frage beantwortet, und sie
    kennt den Unterschied zwischen geteilter Kasse und Summe der Einzelkonten.

    Der Haendler war nie betroffen: er liest `broker.equity`
    (`live/paper.py:833`). Dieses Tor entscheidet nur ueber Handbestaetigungen.

    Steht auf Modulebene statt im Abschluss, damit es gegen einen echten
    `PaperStateStore` pruefbar ist statt gegen eine Nachbildung davon.
    """
    speicher = PaperStateStore(services.config.engine.paths.data_dir / services.state_name)
    kapital, _hoch, _gepoolt = account_equity(speicher, services.config)
    return kapital


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"default {DEFAULT_PORT}, or $PORT when the launcher assigns one",
    )
    parser.add_argument(
        "--account",
        choices=sorted(KONTEN),
        default="live",
        help="welches Papierkonto gezeigt wird (live = das bestehende)",
    )
    parser.add_argument("--demo", action="store_true", help="seed one real proposal to look at")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="arm the testnet executor so a held confirmation reaches the exchange",
    )
    args = parser.parse_args(argv)

    state_name, suffix, label, konto_port, einsatz = KONTEN[args.account]
    # Der kontospezifische Port greift nur, wenn weder --port noch $PORT
    # etwas gesagt hat. Sonst gewinnt immer die ausdrueckliche Angabe.
    if args.port == DEFAULT_PORT and not os.environ.get("PORT"):
        args.port = konto_port

    services = build_default_services()
    services.state_name = state_name
    services.signature_suffix = suffix
    services.account_label = label
    services.deposit_total = einsatz
    services.plan_sizing = PLAN_SIZING[args.account]
    # Echte Historie statt einer leeren Liste, und eine echte Uhr statt 0.
    #
    # Vorher stand hier `recent_trades=[]`, `open_positions=[]` und
    # `now_ms=0`. Damit lasen die drei Verlustsicherungen nichts, und die
    # Abkuehlung rechnete ihre verbleibende Zeit gegen den 01.01.1970 --
    # das Dashboard zeigte also ein Urteil, das nie blockieren konnte.
    #
    # `now_ms=0` war dabei der stillste Teil: `cooldown_ends_at` und die
    # Fensterschnitte in `realised_today` haengen daran, und mit 0 liegt
    # JEDER Trade ausserhalb jedes Fensters.
    journal = JournalStore(services.config.engine.paths.data_dir / "journal.sqlite")

    def _konto_jetzt() -> AccountState:
        """Der Kontozustand bei JEDER Pruefung neu -- nicht einmal beim Start.

        Hier stand eine einmalige Zuweisung. Zwei Folgen, beide gemessen in
        `tests/test_confirm_path_is_a_gate.py`:

        * `open_positions` wurde nicht uebergeben, also war die Liste leer und
          die beiden Positionspruefungen rechneten `0 >= 5` und `0 >= 1`. Sie
          konnten nicht ausloesen. Genau der Defekt, den `live/book.py` fuer
          den Papierhaendler beschreibt und behoben hat.
        * `now_ms` war der Startzeitpunkt. `realised_today` schneidet mit
          `cutoff = now_ms - DAY_MS`, also wuchs das "Tagesfenster" zu
          `[T0-24h, unendlich)` und sammelte jeden spaeteren Verlust ein.
          Gemessen: ein Verlust zehn Tage nach dem gefrorenen Zeitpunkt zaehlt
          als "heute". Das irrt auf die sichere Seite, ist aber falsch.

        Offene Positionen kommen vom Executor, wenn scharf geschaltet ist.
        Unarmiert bleibt die Liste leer -- unbedenklich, weil unarmiert nichts
        gesendet werden kann, und `_assert_trading_allowed` blockt ohnehin,
        wenn gar kein Zustand da ist.

        Das Kapital kommt aus `kontostand()` -- dem Kontospeicher, nicht der
        Konfiguration. Warum das ein behobener Fehler ist, steht dort.
        """
        offen: list[Position] = []
        if services.executor is not None:
            try:
                offen = list(services.executor.open_positions())
            except Exception as exc:
                # Ein Fehler hier darf NICHT als "keine Positionen" gelesen
                # werden: das waere wieder `0 >= 5`. Stattdessen kein Zustand,
                # und das Tor blockt.
                print(f"  offene Positionen nicht abrufbar: {exc}", file=sys.stderr)
                raise
        return AccountState.from_history(
            equity=kontostand(services),
            history=closed_trades(journal, signature=_signatur(services)),
            now_ms=SystemClock().now_ms(),
            open_positions=offen,
        )

    services.account_provider = _konto_jetzt

    if args.execute and not _arm(services):
        return 2

    if args.demo:
        print("Seeding a demo proposal:")
        seed_demo(services)

    # Resolved before the banner, or the banner names a port nothing listens on.
    port = _free_port(args.host, args.port)
    if port != args.port:
        print(f"\n  port {args.port} was already in use, so this one is on {port}")

    print(f"\n  http://{args.host}:{port}")
    if services.executor is None:
        print("  no exchange is connected; confirming reports what would have been sent\n")
    else:
        network = "testnet" if load_secrets().bybit.testnet else "MAINNET -- REAL MONEY"
        print(f"  armed against Bybit {network}; a held confirmation places a real order\n")

    uvicorn.run(create_app(services), host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
