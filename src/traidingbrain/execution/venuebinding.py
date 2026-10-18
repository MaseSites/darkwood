"""Eine Venue je Lauf — als Wert, der nur kohärent konstruierbar ist.

**Der Anlass steht in `audit/P0A_LEGACY_FREEZE.md`, Gruppe Venue-Reinheit.**
`config/settings.yaml` sagt `exchange.name: binance`. `execution/order.py:91`
hat `venue_name: str = "bybit"` als Vorgabewert, und `run_dashboard.py:144`
sowie `run_live.py:230` bauen den Executor ohne dieses Argument. Die
Driftprüfung beim Bestätigen (`api/app.py:813`) liest dagegen
`services.prices`, gebaut aus `config.engine.exchange.name`. Das ergibt:

    Kerzen, Analyse, Entry/Stop/Ziel     BINANCE
    Driftprüfung (15 bps) beim Bestätigen BINANCE
    Instrumentregeln (Tick, min_qty, MMR) BYBIT
    die Order selbst                      BYBIT

Der Pfad ist schlafend, weil das Dashboard ohne `--execute` läuft. Die
Bybit-Testnet-Schlüssel sind hinterlegt, also ist er ein Schalter entfernt.

**Warum ein Wert und keine Prüffunktion.** Eine Funktion muss aufgerufen
werden, und genau das Aufrufen ist hier ausgeblieben: `data/venue.py:venue()`
existiert seit Langem, `ExecutionPolicy` prüft ihre eigenen Gebühren, und die
fünf Entscheidungen konnten trotzdem auseinanderlaufen, weil keine Zeile Code
sie zusammen betrachtet hat. Ein Wert, der inkohärent nicht entstehen kann,
lässt sich nicht vergessen.

**Die Venue ist abgeleitet, nicht gespeichert.** `venue` als sechstes Feld
wäre eine sechste Stelle, die abweichen kann.

**Was dieser Wert NICHT leistet.** Er sagt, dass alle Entscheidungen auf
dieselbe Börse zeigen. Er sagt nichts darüber, ob die Zugangsdaten zu dieser
Börse gehören -- ein Binance-Executor mit Bybit-Schlüsseln ist kohärent im
Sinne dieses Objekts und trotzdem falsch. Diese Prüfung gehört an die Stelle,
die die Schlüssel lädt, und ist in P1b separat verdrahtet.
"""

from __future__ import annotations

import dataclasses

from traidingbrain.data.venue import SUPPORTED
from traidingbrain.execution.policy import ExecutionPolicy


class IncoherentVenueError(RuntimeError):
    """Zwei Entscheidungen eines Laufs zeigen auf verschiedene Börsen.

    `RuntimeError` und nicht `ValueError`: das ist kein ungültiger Eingabewert,
    sondern ein Lauf, der nicht stattfinden darf.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class VenueBinding:
    """Die fünf venue-tragenden Entscheidungen eines Laufs, zusammen geprüft."""

    analysis_venue: str
    """Woher die Kerzen kommen -- `config.engine.exchange.name`."""

    price_check_venue: str
    """Woher der Preis für die Driftprüfung kommt -- `services.prices`."""

    instrument_spec_venue: str
    """Woher Tick, qty_step, min_notional, MMR und max_leverage kommen."""

    execution_venue: str
    """Wohin die Order geht."""

    policy: ExecutionPolicy
    """Der Gebührenplan und die Ordertypen. Trägt ihre Venue selbst."""

    testnet: bool
    """Testnet und Mainnet sind verschiedene Läufe, nicht eine Einstellung."""

    def __post_init__(self) -> None:
        felder = {
            "analysis_venue": self.analysis_venue,
            "price_check_venue": self.price_check_venue,
            "instrument_spec_venue": self.instrument_spec_venue,
            "execution_venue": self.execution_venue,
            "policy": self.policy.venue,
        }
        verschieden = sorted(set(felder.values()))
        if len(verschieden) > 1:
            zuordnung = ", ".join(f"{k}={v!r}" for k, v in felder.items())
            raise IncoherentVenueError(
                f"Ein Lauf, fuenf Boersen-Entscheidungen, aber "
                f"{len(verschieden)} verschiedene Boersen: {verschieden}. "
                f"{zuordnung}. Dieser Lauf findet nicht statt."
            )

        venue = verschieden[0]
        if venue not in SUPPORTED:
            raise IncoherentVenueError(
                f"Venue {venue!r} ist nicht unterstuetzt. Bekannt: "
                f"{sorted(SUPPORTED)}. Kohaerent und unbekannt ist kein "
                f"zulaessiger Zustand -- es gibt dann weder eine "
                f"Gebuehrentabelle noch Instrumentregeln."
            )

    @property
    def venue(self) -> str:
        """Die eine Börse dieses Laufs. Abgeleitet, nicht gespeichert."""
        return self.analysis_venue

    def fingerprint(self) -> str:
        """Was in `run_signature` eingeht.

        In der Legacy-Signatur stand die Venue NICHT. Darum ist aus den Daten
        nicht entscheidbar, ob die 7.335 Trades unter Bybit- oder
        Binance-Regeln entstanden -- die Antwort steht nur in einem Kommentar
        in `domain/market.py:70`.
        """
        netz = "testnet" if self.testnet else "mainnet"
        return f"{self.venue}|{netz}|{self.policy.fingerprint()}"
