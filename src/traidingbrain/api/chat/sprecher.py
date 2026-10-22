"""Der Sprecher des Chats: Claude ueber die installierte CLI.

Er formuliert und schlaegt vor. Er urteilt nie -- das Urteil kommt allein aus der
Regelpruefung, und `Antwort` hat bewusst kein Feld, in das ein Urteil passen
koennte: was Claude zusaetzlich liefert (etwa `"angenommen": true`), wird beim
Lesen verworfen.

Transport und Entpackung sind die der Abo-CLI aus `brain/subscription.py`
(`run_cli`, `unwrap`), nicht nachgebaut.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError, field_validator

from traidingbrain.api.chat.modelle import Lage, Vorschlag
from traidingbrain.brain.subscription import (
    SubscriptionUnavailableError,
    _cli_environment,
    _extract_json,
    run_cli,
)

#: Wie viele Verlaufszeilen in die Eingabe gehen.
VERLAUF_ZEILEN = 10

#: So lange gilt ein Probeaufruf von `status()`.
STATUS_CACHE_S = 60.0

#: Wie lange der Versions-Probeaufruf hoechstens laeuft.
PROBE_TIMEOUT_S = 15

#: Der Systemtext geht als Datei an die CLI (`--system-prompt-file`): er ersetzt den
#: Standard-Systemtext von Claude Code, statt nur neben ihm in der Eingabe zu stehen.
SYSTEM_PROMPT_DATEI = Path(__file__).with_name("system_prompt.md")

NICHT_LESBAR = "Antwort nicht lesbar"


@dataclass
class Antwort:
    """Was der Sprecher zurueckgibt; ohne Urteil."""

    text: str
    vorschlag: Vorschlag | None = None
    bedenken: list[str] = field(default_factory=list)
    fehler: str | None = None


class Sprecher(Protocol):
    def sprich(self, nachricht: str, lage: Lage, verlauf: list[tuple[str, str]]) -> Antwort: ...


class _Roh(BaseModel):
    """Das Schema, das Claude liefern soll; unbekannte Felder werden ignoriert."""

    antwort: str
    vorschlag: Vorschlag | None = None
    bedenken: list[str] = []

    @field_validator("bedenken", mode="before")
    @classmethod
    def _null_ist_leer(cls, v: object) -> object:
        """`"bedenken": null` heisst keine Bedenken -- kein Grund fuer eine Nachfrage."""
        return [] if v is None else v


def _lage_json(lage: Lage) -> str:
    """Die Lage fuer den Prompt: ohne AccountState-Objekt, dafuer Equity und Positionen."""
    daten = lage.model_dump(mode="json", exclude={"konto"})
    daten["equity"] = lage.konto.equity
    daten["positionen"] = [
        [p.symbol, getattr(p.side, "value", p.side)] for p in lage.konto.open_positions
    ]
    return json.dumps(daten, ensure_ascii=False, indent=2)


def _version_probe(pfad: str) -> bool:
    """`claude --version`: billig, schickt keinen Prompt."""
    try:
        fertig = subprocess.run(
            [pfad, "--version"],
            capture_output=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return fertig.returncode == 0


class ClaudeSprecher:
    """Spricht ueber die Claude-CLI; `lauf` ist austauschbar (Tests rufen nie die CLI)."""

    def __init__(
        self,
        lauf: Callable[[str], tuple[str | None, str | None]] | None = None,
        *,
        which: Callable[[str], str | None] = shutil.which,
        probe: Callable[[str], bool] = _version_probe,
        uhr: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lauf = lauf or self._cli_lauf()
        self._which = which
        self._probe = probe
        self._uhr = uhr
        self._probe_stand: tuple[float, bool] | None = None
        self._anmeldung_fehlt = False

    @staticmethod
    def _cli_lauf() -> Callable[[str], tuple[str | None, str | None]]:
        """Die echte CLI, in einem leeren Arbeitsverzeichnis (kein CLAUDE.md, keine Tools),
        mit dem eigenen Systemtext statt dem von Claude Code."""
        arbeitsordner = tempfile.mkdtemp(prefix="darkwood-chat-")
        exe = shutil.which("claude") or "claude"
        return partial(
            run_cli,
            executable=exe,
            system_file=str(SYSTEM_PROMPT_DATEI),
            workspace=arbeitsordner,
            env=_cli_environment(),
        )

    # -- Eingabe ------------------------------------------------------------ #

    def _eingabe(self, nachricht: str, lage: Lage, verlauf: list[tuple[str, str]]) -> str:
        """Lage, Verlauf und Nachricht; der Systemtext geht getrennt als Datei an die CLI."""
        zeilen = "\n".join(f"{rolle}: {text}" for rolle, text in verlauf[-VERLAUF_ZEILEN:])
        return (
            f"## Lagebild\n{_lage_json(lage)}\n\n"
            f"## Bisheriger Verlauf\n{zeilen or '(leer)'}\n\n"
            f"## Nachricht des Nutzers\n{nachricht}\n"
        )

    # -- Sprechen ----------------------------------------------------------- #

    def sprich(self, nachricht: str, lage: Lage, verlauf: list[tuple[str, str]]) -> Antwort:
        eingabe = self._eingabe(nachricht, lage, verlauf)
        roh = ""
        for versuch in range(2):
            try:
                text, _sid = self._lauf(eingabe)
            except SubscriptionUnavailableError as e:
                self._anmeldung_fehlt = True
                return Antwort(text="", fehler=f"Claude nicht erreichbar: {str(e)[:200]}")
            self._anmeldung_fehlt = False
            if text is None:
                return Antwort(text="", fehler="Claude hat nicht geantwortet")
            roh = text
            try:
                r = _Roh.model_validate_json(_extract_json(roh))
            except (ValidationError, ValueError) as e:
                if versuch == 0:
                    eingabe += (
                        "\n\nDeine letzte Antwort war nicht lesbar. Hier ist sie, danach der "
                        f"Fehler:\n\n{roh[:2000]}\n\n{str(e)[:1000]}\n\n"
                        "Antworte nur mit dem korrigierten JSON-Objekt."
                    )
                continue
            return Antwort(text=r.antwort, vorschlag=r.vorschlag, bedenken=list(r.bedenken))
        return Antwort(text=roh[:2000], vorschlag=None, fehler=NICHT_LESBAR)

    # -- Status ------------------------------------------------------------- #

    def status(self) -> Literal["bereit", "nicht_angemeldet", "nicht_installiert"]:
        """Ohne Chat-Prompt: `claude --version` (60 s gecacht) plus der Befund des letzten
        echten Aufrufs -- einen Anmeldefehler sieht nur ein echter Aufruf."""
        pfad = self._which("claude")
        if pfad is None:
            return "nicht_installiert"
        jetzt = self._uhr()
        if self._probe_stand is None or jetzt - self._probe_stand[0] >= STATUS_CACHE_S:
            self._probe_stand = (jetzt, self._probe(pfad))
        if not self._probe_stand[1]:
            return "nicht_installiert"
        return "nicht_angemeldet" if self._anmeldung_fehlt else "bereit"
