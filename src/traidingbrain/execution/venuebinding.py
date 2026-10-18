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

    incoherence_reason: str = ""
    """Der ausgeschriebene Grund, warum dieser Lauf zwei Börsen mischt.

    **Leer heisst: er mischt sie nicht.** Das Kohärenztor bleibt scharf; dieses
    Feld ist kein Schalter, der es abschaltet, sondern die Pflicht, die
    Ausnahme zu benennen.

    Der Anlass ist gemessen. Am 18.10.2026 hat `research()` den
    Legacy-Replay abgewiesen -- zu Recht: er liest Binance-Kerzen und baut
    seine Instrumentregeln aus `DEFAULT_SPEC`, dessen Zahlen Bybits sind. Das
    Tor hat damit genau den Widerspruch gefunden, für den es gebaut wurde.

    Nur: die eingefrorene Population IST so entstanden, und sie muss
    reproduzierbar bleiben. Ein Lauf, der sie nachrechnet, braucht also einen
    Weg, inkohärent zu sein -- und der Weg muss drei Dinge leisten, damit er
    keine Aufweichung ist:

    * Er heisst `legacy_incoherent` und nicht `research`, also kann ihn
      niemand versehentlich treffen.
    * Er verlangt diesen Grund als Text. Ein Feld, das man füllen muss, wird
      gelesen; ein `allow=True` wird kopiert.
    * Er kann **nicht ausführen**. `execution_venue` ist dort immer `None`,
      und das ist die eigentliche Sicherung: ein inkohärenter Lauf darf
      messen, niemals senden.

    Der Grund steht im Fingerprint, also sind ein kohärenter und ein
    inkohärenter Lauf nie derselbe Lauf.
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
    def legacy_incoherent(
        cls,
        *,
        data_venue: str,
        price_venue: str,
        price_environment: Environment,
        instrument_spec_venue: str,
        policy: ExecutionPolicy,
        reason: str,
    ) -> VenueBinding:
        """Ein Lauf, der zwei Börsen mischt -- benannt, begründet, ohne Senden.

        Siehe `incoherence_reason` für das Warum. Hier steht nur, was dieser
        Konstruktor **nicht** kann: ausführen. `execution_venue` ist `None`
        und ist kein Parameter, also gibt es keinen Aufruf, der das ändert.

        Und er bleibt streng, wo Strenge nichts kostet: eine *kohärente*
        Bindung durch diesen Weg zu bauen ist ein Fehler, denn dann ist der
        Grund gegenstandslos und würde als Rauschen in jeden Fingerprint
        wandern.
        """
        if not reason.strip():
            raise IncoherentVenueError(
                "legacy_incoherent ohne Grund. Der Grund ist der ganze "
                "Unterschied zu einer Aufweichung des Tores -- ein Feld, das "
                "man fuellen muss, wird gelesen."
            )
        venues = {data_venue, price_venue, instrument_spec_venue, policy.venue}
        if len(venues) == 1:
            raise IncoherentVenueError(
                f"legacy_incoherent fuer einen KOHAERENTEN Lauf ({venues.pop()!r}). "
                f"Dann ist der Grund gegenstandslos und verschmutzt jeden "
                f"Fingerprint. `research()` ist der richtige Weg."
            )
        return cls(
            data_venue=data_venue,
            price_venue=price_venue,
            price_environment=price_environment,
            instrument_spec_venue=instrument_spec_venue,
            policy=policy,
            execution_venue=None,
            execution_environment=None,
            mainnet_approved=False,
            incoherence_reason=reason.strip(),
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
            if not self.incoherence_reason:
                raise IncoherentVenueError(
                    f"Ein Lauf, {len(felder)} Boersen-Entscheidungen, aber "
                    f"{len(verschieden)} verschiedene Boersen: {verschieden}. "
                    f"{zuordnung}. Dieser Lauf findet nicht statt. "
                    f"Ein Lauf, der eine Legacy-Population nachrechnet und "
                    f"darum inkohaerent sein MUSS, nimmt "
                    f"`VenueBinding.legacy_incoherent(reason=...)` -- der kann "
                    f"nicht ausfuehren."
                )
            # Die benannte Ausnahme. Sie darf messen und niemals senden: ein
            # inkohaerenter Lauf weiss nicht, welche Instrumentregeln an der
            # Boerse gelten, an die er sendet.
            if self.execution_venue is not None:
                raise IncoherentVenueError(
                    f"Ein inkohaerenter Lauf darf nicht ausfuehren, auch nicht "
                    f"mit Grund ({self.incoherence_reason!r}). {zuordnung}. "
                    f"Er weiss nicht, welche Regeln an der Zielboerse gelten."
                )
            for venue in verschieden:
                if venue not in SUPPORTED:
                    raise IncoherentVenueError(
                        f"Venue {venue!r} ist nicht unterstuetzt. Bekannt: "
                        f"{sorted(SUPPORTED)}."
                    )
            return

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
        """Diese Bindung als eine lesbare Zeile, fürs Banner und für Tests.

        **Nicht** der Schlüssel einer gespeicherten Zeile, und das stand hier
        bis zum 18.10.2026 anders („Was in `run_signature` eingeht"). Es war
        nie verdrahtet: `run_signature` kennt die Venue nicht, und genau das
        war der Befund -- aus den Daten ist nicht entscheidbar, ob die 7.335
        Trades unter Bybit- oder Binance-Regeln entstanden; die Antwort stand
        nur in einem Kommentar in `domain/market.py:70`.

        Geschlossen wird das von `journal/identity.py`, das die Venues als
        eigene Felder trägt und feldweise beweist, dass jedes den Stempel
        bewegt. Diese Methode bleibt, weil eine Bindung in einer Zeile lesbar
        sein soll -- aber sie trägt keine Identität mehr, und darum darf sie
        sich auch ändern, ohne etwas zu verwaisen.
        """
        if self.execution_venue is None:
            ausfuehrung = "exec=keine"
        else:
            ausfuehrung = f"exec={self.execution_venue}/{self.execution_environment}"
        freigabe = "approved" if self.mainnet_approved else "unapproved"
        # Der Grund gehoert hinein, sonst waeren ein kohaerenter und ein
        # bewusst inkohaerenter Lauf dieselbe Zeile.
        mischung = f"|incoherent={self.incoherence_reason}" if self.incoherence_reason else ""
        return (
            f"data={self.data_venue}|"
            f"price={self.price_venue}/{self.price_environment}|"
            f"spec={self.instrument_spec_venue}|"
            f"{ausfuehrung}|{freigabe}|{self.policy.fingerprint()}{mischung}"
        )
