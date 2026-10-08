"""Ein Prozess je Rolle, vom Betriebssystem erzwungen.

**Warum das existiert.** Am 07.10.2026 liefen zwei Papierhändler gleichzeitig.
Sie verdoppelten die Anfragerate gegen dieselbe IP, liefen ins Rate-Limit von
Binance und erzeugten 58 fehlgeschlagene Zyklen -- und keiner der beiden
merkte etwas, weil ein fehlgeschlagener Zyklus für sich genommen normal
aussieht. Gefunden wurde es erst, als jemand die Prozessliste zählte.

Der Versuch, das mit `pkill -f` zu verhindern, taugt hier nicht: unter Windows
erreicht es die Prozesse nicht, und das Zählen von Zeilen in einer
Prozessliste zählt die Startprogramme mit, nicht die Läufe. Beides steht in
den Projektnotizen als Falle.

**Was hier stattdessen passiert.** Eine Sperrdatei, exklusiv gesperrt durch
das Betriebssystem: `msvcrt.locking` unter Windows, `fcntl.flock` sonst. Der
entscheidende Vorteil gegenüber einer selbstgebauten PID-Prüfung ist, dass das
Betriebssystem die Sperre **beim Prozessende von sich aus freigibt** -- auch
bei einem Absturz, einem Kill oder einem Stromausfall. Es gibt deshalb keine
verwaiste Sperre, die ein späterer Start erst mühsam als veraltet erkennen
müsste. Genau diese Erkennung ist die Stelle, an der selbstgebaute Locks
falsch werden.

Die Datei trägt die PID und die Startzeit, damit ein Mensch im Zweifel sieht,
wer die Sperre hält. Diese Angaben sind **Diagnose, nicht Mechanik**: die
Entscheidung fällt allein an der Sperre des Betriebssystems.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import sys
from pathlib import Path
from types import TracebackType

# Plattformexklusive Module, darum die Verzweigung hier oben und nicht in den
# Funktionen: `msvcrt` existiert unter POSIX nicht und `fcntl` nicht unter
# Windows. `sys.platform` ist die Bedingung, die auch mypy versteht.
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


#: Der Byte-Versatz, an dem gesperrt wird -- weit hinter allem, was die Datei
#: an Text enthält.
#:
#: **Und dahinter steckt ein Plattformunterschied, den ein Test gefunden hat.**
#: `msvcrt.locking` ist unter Windows eine *mandatory* Sperre: solange sie
#: gehalten wird, verweigert das Betriebssystem jedem anderen Handle sogar das
#: LESEN des gesperrten Bereichs -- auch demselben Prozess. Eine Sperre bei
#: Versatz 0 hätte damit die Diagnose unlesbar gemacht, die sie erklären soll,
#: und `holder()` hätte "unbekannt" gemeldet, während alles in Ordnung war.
#: `fcntl.flock` ist dagegen beratend und sperrt die ganze Datei, lässt Lesen
#: aber zu. Ein reservierter Bereich hinter dem Text verhält sich auf beiden
#: Systemen gleich.
LOCK_OFFSET = 4096

#: Feste Breite des Diagnosetextes, deutlich kleiner als `LOCK_OFFSET`. Damit
#: endet die Datei weit vor der Sperre, und wer sie liest, liest nur Text.
NOTE_WIDTH = 120


class AlreadyRunningError(RuntimeError):
    """Eine andere Instanz derselben Rolle hält die Sperre."""


def _lock_exclusive(handle: int) -> None:
    """Exklusive, nicht blockierende Sperre. Wirft OSError, wenn belegt."""
    if sys.platform == "win32":
        # Ein Byte, und zwar bei LOCK_OFFSET: der Text davor bleibt lesbar.
        os.lseek(handle, LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: int) -> None:
    # Beim Prozessende gibt das Betriebssystem ohnehin frei. Ein Fehler beim
    # Entsperren darf den Aufräumpfad nicht sprengen.
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            os.lseek(handle, LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)


class SingleInstance:
    """Kontextmanager, der genau einen Prozess je `role` zulässt.

        with SingleInstance("papertrade", directory=config.paths.data_dir):
            run()

    Der zweite Start wirft `AlreadyRunningError` mit der PID des ersten -- und
    zwar **bevor** er eine Verbindung aufbaut oder einen Zustand schreibt.
    """

    def __init__(self, role: str, *, directory: Path) -> None:
        self.role = role
        self.path = Path(directory) / f"{role}.lock"
        self._handle: int | None = None

    def holder(self) -> str:
        """Was in der Sperrdatei steht, für die Fehlermeldung. Nur Diagnose."""
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return "unbekannt"

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # `O_CREAT` ohne `O_TRUNC`: der Inhalt des Vorgängers bleibt lesbar,
        # solange wir die Sperre nicht haben. Wer die Datei leert, bevor er
        # weiss, ob er sie halten darf, loescht die Diagnose des anderen.
        handle = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            _lock_exclusive(handle)
        except OSError as problem:
            other = self.holder()
            os.close(handle)
            raise AlreadyRunningError(
                f"{self.role} laeuft bereits ({other}). "
                f"Sperre: {self.path}"
            ) from problem
        self._handle = handle
        stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        note = f"pid={os.getpid()} seit={stamp}".encode()
        # Nur den Textbereich kürzen, nicht die Datei: das gesperrte Byte liegt
        # bei LOCK_OFFSET, und eine Kürzung darunter würde es wegschneiden.
        os.lseek(handle, 0, os.SEEK_SET)
        # Auf feste, KURZE Breite auffüllen. Kurz, weil das gesperrte Byte bei
        # LOCK_OFFSET hinter dem Dateiende liegen muss: Windows sperrt einen
        # Bereich auch jenseits von EOF, und nur dann liest ein `read_text`
        # (das bis EOF liest) nicht in die Sperre hinein. Mit Auffüllung BIS
        # LOCK_OFFSET war genau das der Fehler -- der Test hat ihn gefunden.
        # Feste Breite statt Kürzen, weil ein `truncate` unter eine gehaltene
        # Sperre hinein nicht auf jedem System erlaubt ist.
        os.write(handle, note.ljust(NOTE_WIDTH - 1)[: NOTE_WIDTH - 1] + b"\n")
        os.fsync(handle)

    def release(self) -> None:
        if self._handle is None:
            return
        _unlock(self._handle)
        os.close(self._handle)
        self._handle = None
        # Die Datei bleibt liegen. Sie zu löschen wäre ein Wettlauf: zwischen
        # Entsperren und Löschen kann ein anderer Prozess sie bereits halten,
        # und dann löschen wir die Sperre eines Fremden.

    def __enter__(self) -> SingleInstance:
        self.acquire()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.release()
