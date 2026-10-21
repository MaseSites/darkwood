"""Welche Trades zur laufenden Konfiguration gehören — an EINER Stelle.

**Der Anlass ist ein Fehler, der zweimal dasselbe rechnete.** Am 16.10.2026
zeigte das Dashboard „28 Trades vorwärts · Mittel +0,294 R". Diese 28
zerfielen in VIER Konfigurationen — nach beiden Feldern gruppiert, so wie
`era_count` zählt:

    n=18   +0.3938 R   Signatur LEER                     Codestand LEER
    n= 7   +0.1707 R   ...|0.08|M15|refused-v1           3edf58b5250c
    n= 2   -1.0277 R   ...|0.08|M15|refused-v1           Codestand LEER
    n= 1   +2.0029 R   ...refused-v1|portfolio|cap5      d8c7f12104e4

Hier stand zuerst „drei Konfigurationen" mit den mittleren neun als EINER
Zeile (-0.0956 R). Das war nach der Signatur allein gruppiert, und genau
diese Verkürzung widerlegt dieses Modul: die neun teilen sich in sieben mit
Codestand und zwei ohne, +0.1707 R gegen -1.0277 R. Eine Beschreibung der
Epochen, die den Codestand weglässt, kann die Epochen nicht zählen.

Die zwei Zeilen ohne Codestand bei vorhandener Signatur sind die Spur eines
behobenen Fehlers: der Stempel wurde beim ersten Journalschreiben träge von
der Platte gelesen und fehlte, wenn das fehlschlug.

Unter `portfolio` riskiert ein Trade 120 USDT, unter der Vorgängerin 10. Ein
Mittelwert darüber beantwortet keine Frage, und auf dem Bildschirm liest er
sich als Vorteil des Systems.

Repariert wurde zuerst `api/portfolio.py` — und das Dashboard zeigte weiter
die alte Zahl, weil seine Schlagzeile aus `api/paper.py` kommt, das dieselbe
Rechnung ein zweites Mal anstellt. Die neue Beschriftung stand dann über den
alten Zahlen, was schlimmer ist als beides für sich.

Darum hier, und darum nur hier. Zwei Stellen, die denselben Satz berechnen,
laufen auseinander; das Projekt hat das bei `SAFETY_RULES` schon einmal
bezahlt (`learn/overrides.py`).

**Was „dieselbe Konfiguration" heisst, und warum beides nötig ist.**
`run_signature` deckt die Einstellungen — Startkapital, Setup-Liste,
Kostendeckel, Signalebene, Grössenbemessung, Platzdeckel. `decision_version`
deckt den Code des Entscheidungspfades. Eine Änderung an einem von beiden
kann ändern, welche Trades entstehen, also müssen beide stimmen.

Eine Zeile ohne das eine oder das andere fällt heraus, und das ist richtig:
18 der 28 Vorwärtstrades trugen gar keine Signatur und sind aus den Daten
keiner Konfiguration zuzuordnen. Sie verschwinden deshalb nicht — `eras`
zählt sie mit, damit „es gibt sie nicht mehr" nicht mit „sie zählen hier
nicht mit" verwechselt wird.
"""

from __future__ import annotations

from collections.abc import Iterable

from traidingbrain.config.settings import AppConfig
from traidingbrain.journal.record import JournalEntry
from traidingbrain.journal.version import decision_version, run_signature


def current_era(
    entries: Iterable[JournalEntry], config: AppConfig, *, signature: str | None = None
) -> list[JournalEntry]:
    """Die Trades, die unter der laufenden Konfiguration entstanden sind.

    Beides muss stimmen: dieselbe `run_signature` UND derselbe
    `decision_version`. Siehe das Modul-Docstring für den Grund.

    **`signature` ist nötig, sobald ein Konto seine eigene Grössenbemessung
    trägt.** Das Plankonto hängt `|plan30x7r15f` an seine Signatur;
    `run_signature(config)` kennt diesen Zusatz nicht und kann ihn nicht
    kennen, weil er aus `config_offen/plan.yaml` kommt und nicht aus der
    Engine-Konfiguration. Der Vergleich traf darum **nie**: am 21.10.2026 lagen
    acht geschlossene Trades unter genau dieser Signatur im Journal, und die
    Schlagzeile stand auf „0 Trades", während die Markttabelle darunter aus
    denselben Zeilen -40,24 USD auswies.

    Das ist derselbe Fehlertyp wie am 16.10.: nicht eine falsche Zahl, sondern
    zwei Zahlen aus einer Quelle, die sich widersprechen. Wer `signature`
    übergibt, vergleicht gegen die Signatur, unter der die Zeilen auch
    geschrieben wurden.
    """
    erwartet = signature or run_signature(config)
    stamp = decision_version()
    return [
        entry
        for entry in entries
        if entry.run_signature == erwartet and entry.decision_version == stamp
    ]


def era_count(entries: Iterable[JournalEntry]) -> int:
    """Über wie viele (Signatur, Codestand)-Paare sich diese Trades verteilen.

    Eins heisst: die Schlagzeile deckt alles ab. Mehr heisst: es gibt ältere
    Trades, die nicht mitzählen — eine Aussage, kein Datenverlust.
    """
    return len({(entry.run_signature, entry.decision_version) for entry in entries})
