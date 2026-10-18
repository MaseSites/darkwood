"""Eine Venue je Lauf, getrennte Umgebungen — als Wert, der nur kohärent entsteht.

**Der Anlass steht in `audit/P0A_LEGACY_FREEZE.md`, Gruppe Venue-Reinheit.**
`config/settings.yaml` sagt `exchange.name: binance`. `execution/order.py:91`
hat `venue_name: str = "bybit"` als Vorgabewert, und `run_dashboard.py:144`
sowie `run_live.py:230` bauen den Executor ohne dieses Argument. Die
Driftprüfung beim Bestätigen (`api/app.py:813`) liest dagegen
`services.prices`, gebaut aus `config.engine.exchange.name`. Das ergibt:

    Kerzen, Analyse, Entry/Stop/Ziel      BINANCE
    Driftprüfung (15 bps) beim Bestätigen BINANCE
    Instrumentregeln (Tick, min_qty, MMR) BYBIT
    die Order selbst                      BYBIT

**Gleiche Venue heisst nicht gleiche Umgebung.** Ein Mainnet-Preischeck mit
Testnet-Ausführung ist eine absichtliche Kombination: die Preisprobe soll
gegen den echten Markt laufen, die Order gegen das Testnet. Darum sind
`price_environment` und `execution_environment` zwei Felder.

`run_dashboard.py:173` übergab `testnet=secrets.bybit.testnet` an die
**Binance**-Preisquelle — koppelte also die Preisumgebung an die
Ausführungsumgebung einer anderen Börse. Mit `testnet=true` und
`venue=binance` ruft `venue.build` `enable_demo_trading` und leitet auf
`demo-dapi.binance.com`; die Driftprüfung verglich dann gegen Demo-Preise.
`run_live.py:96` setzt für dieselbe Quelle ausdrücklich `testnet=False` mit
der Begründung „Prices come from mainnet". Die beiden Runner widersprachen
sich bei derselben Entscheidung.

**Warum ein Wert und keine Prüffunktion.** Eine Funktion muss aufgerufen
werden, und genau das ist ausgeblieben: `data/venue.py:venue()` existiert seit
Langem, `ExecutionPolicy` prüft ihre eigenen Gebühren, und die Entscheidungen
liefen trotzdem auseinander, weil keine Zeile Code sie zusammen betrachtet
hat. Ein Wert, der inkohärent nicht entstehen kann, lässt sich nicht
vergessen.

**Bybit ist die einzige ausführbare Venue** (Master-Direktive 03 Phase 2).
Nicht weil Binance schlechter wäre, sondern weil es nur `BybitCredentials`
gibt (`config/settings.py:461-470`, eingebunden als `Secrets.bybit`). Ein
Binance-Executor hätte keinen Zugangsdatenpfad, und einen spekulativ zu bauen
ist untersagt.

**Eine Folge, die unbequem ist und so gewollt.** Alle Kerzen dieses Projekts
sind Binance. Zusammen mit der Bybit-Beschränkung heisst das: mit den
heutigen Daten ist **keine ausführbare Bindung konstruierbar**. Die Lücke
blockt damit die Ausführung, statt sie falsch zu bepreisen. Wer ausführen
will, braucht Bybit-Daten — oder einen ausdrücklich belegten
Cross-Venue-Anwendungsfall, den dieses Objekt nicht kennt.

**Was dieser Wert NICHT leistet.** Er sagt, dass alle Entscheidungen auf
dieselbe Börse und auf genannte Umgebungen zeigen. Er sagt nichts darüber, ob
die Zugangsdaten zu dieser Börse gehören — diese Prüfung gehört an die Stelle,
die die Schlüssel lädt.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum

from traidingbrain.data.venue import SUPPORTED
from traidingbrain.execution.policy import ExecutionPolicy


class Environment(StrEnum):
    """Welches Netz einer Börse gemeint ist.

    Keine Wahrheitswerte: `testnet=True/False` hat an zwei Stellen dieselbe
    Frage verschieden beantwortet, und ein Wahrheitswert ohne Namen sagt nicht,
    worauf er sich bezieht.
    """

    MAINNET = "mainnet"
    TESTNET = "testnet"


#: Börsen, auf denen dieser Build Orders senden darf.
#:
#: Einelementig, und das ist eine Entscheidung mit Grund: es gibt nur
#: `BybitCredentials`. Die Liste zu erweitern heisst, einen
#: Zugangsdaten-Namensraum zu bauen -- eine Produktentscheidung, nicht eine
#: Konfigurationszeile.
EXECUTABLE_VENUES = frozenset({"bybit"})


class IncoherentVenueError(RuntimeError):
    """Zwei Entscheidungen eines Laufs zeigen auf verschiedene Börsen.

    `RuntimeError` und nicht `ValueError`: das ist kein ungültiger Eingabewert,
    sondern ein Lauf, der nicht stattfinden darf.
    """


class MainnetNotApprovedError(RuntimeError):
    """Mainnet-Ausführung ohne ausdrückliche Freigabe.

    Zwei unabhängige Signale, wie `execution/order.py:98` sie schon verlangt:
    dort braucht es `testnet=False` UND `allow_live=True`, weil „ein einziger
    Konfigurationswert, versehentlich umgestellt, nicht genügen darf".
    """


@dataclasses.dataclass(frozen=True, slots=True)
class VenueBinding:
    """Die venue- und umgebungstragenden Entscheidungen eines Laufs.

    Nicht direkt konstruieren -- `research()` oder `executable()` benutzen. Die
    beiden Namen sagen, ob der Lauf senden darf, und das ist die Angabe, die
    man nicht vergessen können soll.
    """

    data_venue: str
    """Woher die Kerzen und abgeleiteten Reihen kommen."""

    price_venue: str
    """Woher der Preis für die Driftprüfung kommt."""

    price_environment: Environment
    """Mainnet oder Testnet für die Preisprobe. Eigene Angabe, nicht geerbt."""

    instrument_spec_venue: str
    """Woher Tick, qty_step, min_notional, MMR und max_leverage kommen."""

    policy: ExecutionPolicy
    """Gebührenplan und Ordertypen. Trägt ihre Venue selbst."""

    execution_venue: str | None
    """Wohin die Order geht. `None` heisst: dieser Lauf führt nichts aus."""

    execution_environment: Environment | None
    """Mainnet oder Testnet für die Ausführung. `None` bei Forschung."""

    mainnet_approved: bool
    """Ob Mainnet-Ausführung ausdrücklich freigegeben ist.

    Steht auch dann im Fingerprint, wenn gar nicht Mainnet ausgeführt wird:
    sonst wären zwei Läufe mit und ohne erteilte Freigabe nicht zu
    unterscheiden.
    """

    # -- Konstruktoren ------------------------------------------------------ #

    @classmethod
    def research(
        cls,
        *,
        data_venue: str,
        price_venue: str,
        price_environment: Environment,
        instrument_spec_venue: str,
        policy: ExecutionPolicy,
    ) -> VenueBinding:
        """Ein Lauf, der nichts ausführt -- Replay, Backtest, Papierhandel.

        Keine Ausführungsangaben, weil es nichts auszuführen gibt. Sie zu
        verlangen wäre Zeremonie und würde Binance-Forschung unmöglich machen,
        obwohl die Beschränkung nur die Ausführung betrifft.
        """
        return cls(
            data_venue=data_venue,
            price_venue=price_venue,
            price_environment=price_environment,
            instrument_spec_venue=instrument_spec_venue,
            policy=policy,
            execution_venue=None,
            execution_environment=None,
            mainnet_approved=False,
        )

    @classmethod
    def executable(
        cls,
        *,
        data_venue: str,
        price_venue: str,
        price_environment: Environment,
        instrument_spec_venue: str,
        execution_venue: str,
        execution_environment: Environment,
        policy: ExecutionPolicy,
        mainnet_approved: bool = False,
    ) -> VenueBinding:
        """Ein Lauf, der senden darf -- mit allen Angaben und beiden Schranken."""
        return cls(
            data_venue=data_venue,
            price_venue=price_venue,
            price_environment=price_environment,
            instrument_spec_venue=instrument_spec_venue,
            policy=policy,
            execution_venue=execution_venue,
            execution_environment=execution_environment,
            mainnet_approved=mainnet_approved,
        )

    # -- Prüfung ------------------------------------------------------------ #

    def __post_init__(self) -> None:
        felder: dict[str, str] = {
            "data_venue": self.data_venue,
            "price_venue": self.price_venue,
            "instrument_spec_venue": self.instrument_spec_venue,
            "policy": self.policy.venue,
        }
        if self.execution_venue is not None:
            felder["execution_venue"] = self.execution_venue

        verschieden = sorted(set(felder.values()))
        if len(verschieden) > 1:
            zuordnung = ", ".join(f"{k}={v!r}" for k, v in felder.items())
            raise IncoherentVenueError(
                f"Ein Lauf, {len(felder)} Boersen-Entscheidungen, aber "
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

        if self.execution_venue is None:
            if self.execution_environment is not None:
                raise IncoherentVenueError(
                    "execution_environment ohne execution_venue: eine Umgebung "
                    "ohne Boerse ist keine Angabe."
                )
            return

        if self.execution_venue not in EXECUTABLE_VENUES:
            raise IncoherentVenueError(
                f"Auf {self.execution_venue!r} darf dieser Build nicht "
                f"ausfuehren. Ausfuehrbar: {sorted(EXECUTABLE_VENUES)}. Grund: "
                f"es gibt nur BybitCredentials (config/settings.py:461); ein "
                f"Executor fuer eine andere Boerse haette keinen "
                f"Zugangsdatenpfad, und einen spekulativ zu bauen ist "
                f"untersagt."
            )

        if self.execution_environment is None:
            raise IncoherentVenueError(
                "execution_venue ohne execution_environment: ob Testnet oder "
                "Mainnet gemeint ist, wird nicht geraten."
            )

        if (
            self.execution_environment is Environment.MAINNET
            and not self.mainnet_approved
        ):
            raise MainnetNotApprovedError(
                "Mainnet-Ausfuehrung braucht execution_environment=MAINNET UND "
                "mainnet_approved=True. Zwei unabhaengige Signale, weil ein "
                "einziger versehentlich umgestellter Wert nicht genuegen darf "
                "-- dieselbe Begruendung wie in execution/order.py:98."
            )

    # -- Ableitungen -------------------------------------------------------- #

    @property
    def venue(self) -> str:
        """Die eine Börse dieses Laufs. Abgeleitet, nicht gespeichert.

        Ein eigenes Feld wäre eine weitere Stelle, die abweichen kann.
        """
        return self.data_venue

    @property
    def executes(self) -> bool:
        return self.execution_venue is not None

    def fingerprint(self) -> str:
        """Was in `run_signature` eingeht.

        In der Legacy-Signatur stand die Venue NICHT. Darum ist aus den Daten
        nicht entscheidbar, ob die 7.335 Trades unter Bybit- oder
        Binance-Regeln entstanden -- die Antwort steht nur in einem Kommentar
        in `domain/market.py:70`.
        """
        if self.execution_venue is None:
            ausfuehrung = "exec=keine"
        else:
            ausfuehrung = f"exec={self.execution_venue}/{self.execution_environment}"
        freigabe = "approved" if self.mainnet_approved else "unapproved"
        return (
            f"data={self.data_venue}|"
            f"price={self.price_venue}/{self.price_environment}|"
            f"spec={self.instrument_spec_venue}|"
            f"{ausfuehrung}|{freigabe}|{self.policy.fingerprint()}"
        )
