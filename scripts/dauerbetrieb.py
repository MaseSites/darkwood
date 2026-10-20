"""Händler und Dashboards nach einem Neustart von selbst hochfahren.

**Der Anlass.** Am 19.10.2026 wurde der Rechner heruntergefahren. Danach
waren Papierhändler, Wächter und beide Dashboards weg, und das Konto hat
stundenlang nichts getan, ohne dass es jemandem aufgefallen wäre. Ein
Papierkonto, das nur läuft, solange jemand daran denkt, misst die Pausen
mit — und die Pausen stehen in keiner Auswertung.

**Was eingerichtet wird.** Drei Aufgaben in der Windows-Aufgabenplanung, je
eine für den Händler und die beiden Dashboards. Sie starten **bei der
Anmeldung** dieses Benutzers, nicht beim Systemstart: dafür bräuchte es
Administratorrechte, und ein Dashboard nützt ohnehin nur jemandem, der
angemeldet ist.

**Was bewusst NICHT eingerichtet wird: der Wächter.** Der gehört zu einer
Arbeitssitzung und schreibt in ein Sitzungsverzeichnis. Eine Aufgabe, die
ihn mitstartet, würde Meldungen in einen Ordner schreiben, den niemand liest.

---

## Die unbequeme Seite, und sie gehört hierher

**Ein Neustart nach einem Absturz ist eine Verhaltensänderung, keine
Reparatur.** Ein fehlgeschlagener Zyklus ist eine ausgelassene Entscheidung;
wer Fehlschläge behebt, ändert damit, welche Trades überhaupt existieren —
und die Laufsignatur zeichnet das nicht auf. Dieselbe Sache ist in diesem
Projekt am 15.10.2026 schon einmal gemessen worden.

Darum schreibt jeder Start eine Zeile mit Zeitstempel in sein Log, und zwar
als erste. Wer später fragt, warum eine Stichprobe eine Lücke hat, findet
die Antwort dort statt sie zu erraten.

**Die Aufgabe startet nach einem Absturz dreimal neu**, in Abständen von
einer Minute. Mehr nicht: ein Prozess, der fünfmal hintereinander stirbt,
hat ein Problem, das ein sechster Start nicht löst, und eine Endlosschleife
aus Neustarts sieht in jeder Übersicht aus wie ein laufendes System.

    python scripts/dauerbetrieb.py --status
    python scripts/dauerbetrieb.py --einrichten
    python scripts/dauerbetrieb.py --entfernen
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

#: Wohin die Aufgaben schreiben. Im Projekt und nicht im Sitzungsordner,
#: damit die Logs eine Sitzung ueberleben -- sonst waere das Protokoll des
#: Dauerbetriebs selbst nicht dauerhaft.
LOGS = ROOT / "data" / "dienst"

#: Wie oft die Startdatei einen abgestuerzten Prozess neu anlaeuft, und in
#: welchem Abstand.
#:
#: **Warum die Startdatei das tut und nicht die Aufgabenplanung.** Deren
#: `RestartCount`/`RestartInterval` wurden gesetzt und registriert (geprueft:
#: RestartCount 3, RestartInterval PT1M), griffen aber nicht: Haendler
#: getoetet, Rueckgabewert 4294967295 korrekt durchgereicht, Zustand nach 150
#: Sekunden "Ready", nichts kam zurueck. Ihr "Neustart bei Fehler" meint
#: etwas Engeres als "die Aktion endete mit einem Fehler".
#:
#: Eine Schleife in einer Datei, die hier steht, ist dagegen pruefbar -- und
#: genau das war der Punkt: ein Autostart, der nach einem Absturz nichts tut
#: und dabei gesund aussieht, ist schlimmer als keiner.
#:
#: Zwanzig und eine Minute: genug, um ein Netzzucken und eine Stunde
#: Wackelkontakt zu ueberstehen, und begrenzt genug, dass ein dauerhaft
#: kaputtes Skript nach zwanzig Minuten aufgibt statt ewig zu kreisen. Jeder
#: Versuch steht mit Nummer im Log; eine Absturzschleife ist dort als solche
#: zu erkennen und nicht als laufendes System.
MAX_VERSUCHE = 20
NEUSTART_ABSTAND_S = 60

#: Was die Aufgabenplanung zusaetzlich versucht. Schadet nicht, und falls
#: Windows es doch einmal anwendet, ist es die zweite Verteidigungslinie.
NEUSTARTS = 3
NEUSTART_ABSTAND_MIN = 1

#: Wie oft die Aufgabenplanung nachsieht, ob die Aufgabe noch laeuft. Fuenf
#: Minuten sind der Kompromiss: kurz genug, dass eine Luecke klein bleibt,
#: lang genug, dass ein normaler Start (der Haendler laedt ein bis zwei
#: Minuten Historie) nicht mit dem naechsten Anlauf kollidiert.
WACHINTERVALL_MIN = 5


@dataclass(frozen=True, slots=True)
class Aufgabe:
    name: str
    skript: str
    argumente: str
    zweck: str


AUFGABEN: tuple[Aufgabe, ...] = (
    #: `--config-dir config_offen` seit dem 20.10.2026, auf ausdrueckliche
    #: Anweisung des Nutzers: beide Wirtschaftlichkeitstore offen
    #: (Kostendeckel 1.0 statt 0.08, Chance-Risiko 0.01 statt 1.5).
    #:
    #: WAS DAGEGEN SPRICHT, und es ist gemessen, nicht vermutet: ueber 3.553
    #: abgelehnte Signale eines Marktes liegt das Netto bei -0.1464 R je
    #: Trade, gegen -0.0323 R der genommenen. Brutto sind die abgelehnten
    #: fast gleichauf (-0.0334 gegen -0.0013) und treffen sogar OEFTER
    #: (45 % gegen 39 %) -- sie haben nur engere Stops, und dieselbe Gebuehr
    #: frisst dann einen groesseren Teil des Risikos. Genau das behauptet die
    #: Kostenregel. Hochgerechnet auf den gemessenen Takt: rund -29 USD am
    #: Tag, nach 30 Tagen 412 statt 1.000.
    #:
    #: WARUM ES TROTZDEM SO LAEUFT: der Nutzer hat es nach Vorlage dieser
    #: Zahlen entschieden. Die Entscheidung ist seine; die Aufgabe hier ist,
    #: sie sauber auszufuehren und nachlesbar zu machen.
    #:
    #: NICHT global geaendert, und das ist kein Detail: `config/risk.yaml`
    #: haette auch das Konto auf 8787 umgestellt und -- schlimmer -- den
    #: laufenden E17-Replay, dessen Straenge bei einem Absturz neu starten
    #: und dann eine andere Konfiguration gelesen haetten.
    Aufgabe(
        "traidingBrain-plankonto", "scripts/plantrade.py",
        "--config-dir config_offen",
        "Papierhaendler des Plankontos (30 % Margin x 7x), Tore OFFEN.",
    ),
    Aufgabe(
        "traidingBrain-dash-plan", "scripts/run_dashboard.py", "--account plan",
        "Dashboard des Plankontos, 127.0.0.1:8788.",
    ),
    Aufgabe(
        "traidingBrain-dash-live", "scripts/run_dashboard.py", "--account live",
        "Dashboard des bestehenden Kontos, 127.0.0.1:8787.",
    ),
    #: Am 19.10. als Sitzungskind gestartet und mit der Sitzung gestorben --
    #: nach genau einer Stunde, Rueckgabewert 4, den der Sammler gar nicht
    #: kennt (er kennt 0, 2 und eine Ausnahme). Der Wert kam vom Aufrufer.
    #: Ich hatte die Aufnahme bewusst NICHT in den Autostart genommen, mit der
    #: Begruendung, sie sei "eine einmalige Erhebung ueber elf Stunden". Genau
    #: das ist der Grund, warum sie hier hingehoert: elf Stunden sind laenger
    #: als jede Sitzung und laenger als die Zeit bis zum naechsten Standby.
    #: 2.5 und nicht 1, und die Zahl ist gemessen, nicht geraten. Mit `1`
    #: lief die Aufnahme am 20.10. GENAU 70 Sekunden und sammelte danach
    #: 8.190 Fehler "HTTP Error 405" am Stueck -- die Aufgabe stand weiter
    #: auf "Running", schrieb aber nichts mehr. Nach 45 Sekunden Ruhe
    #: antwortete die API wieder normal: eine Drosselung, keine Sperre.
    #:
    #: Die Rechnung dazu: gestern erreichte derselbe Aufruf nur 2.35 s je
    #: Buch (langsamere Antwortzeiten haben uns unbeabsichtigt gebremst),
    #: das sind rund 100 Anfragen/Minute, und er lief 72 Minuten durch.
    #: Heute erreichte er die bestellte 1 s, rund 178 Anfragen/Minute, und
    #: war nach gut einer Minute draussen. Die Grenze liegt dazwischen.
    #: 2.5 s bleibt unter dem, was nachweislich 72 Minuten getragen hat.
    #:
    #: Das heisst zugleich: die Frage nach der Standzeit einer Quote ist
    #: mit ABFRAGEN nicht zu beantworten. 93 % der beobachteten Touch-Leben
    #: dauern genau EINEN Rasterschritt, die wahre Standzeit liegt also
    #: unter dem Raster -- und ein feineres Raster verbietet die Drosselung.
    #: Dafuer braucht es den Websocket-Strom, nicht diesen Sammler.
    Aufgabe(
        "traidingBrain-tape", "scripts/collect_venue_tape.py",
        "--hours 11 --markets BTC,ETH,SOL --book-every 2.5",
        "Buchaufnahme fuer Spread und adverse Selektion (nicht fuer Standzeit).",
    ),
    #: Der zweite Sammler, und er ersetzt den ersten NICHT. Der Strom liefert
    #: gemessene 51 ms Median (46x feiner als die Abfrage) und im Trade-Band
    #: mehr Felder, darunter `maker_position_size_before`. Dafuer sind seine
    #: Buchebenen aggregiert: einzelne Order-IDs gibt es nur per Abfrage
    #: (`order_book_orders` antwortet "Invalid Channel"). Standzeit kann nur
    #: der Strom beantworten, Order-Identitaet nur die Abfrage.
    Aufgabe(
        "traidingBrain-ws", "scripts/collect_venue_ws.py",
        "--hours 11 --markets BTC,ETH,SOL",
        "Websocket-Aufnahme fuer die Standzeit einer Quote.",
    ),
)


def _ps(befehl: str) -> subprocess.CompletedProcess[str]:
    """PowerShell ausfuehren, mit festgenagelter Kodierung auf BEIDEN Seiten.

    Ohne `encoding` entscheidet die Spracheinstellung der Maschine, was durch
    die Leitung geht -- und deutsche Aufgabennamen kommen dann als Zeichensalat
    an. Derselbe Fehler ist heute schon einmal in einem Test gefunden worden.
    """
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", befehl],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )


def startdatei(a: Aufgabe) -> Path:
    """Eine .cmd je Aufgabe -- und der Grund dafuer ist ein behobener Fehler.

    Der erste Entwurf uebergab den ganzen Befehl als Argument an `cmd.exe`,
    mit in PowerShell escapten Anfuehrungszeichen. Die landeten WOERTLICH im
    Argument (`\\"C:\\...\\"`), denn `\\"` ist PowerShell-Syntax und cmd kennt
    sie nicht. Alle drei Aufgaben starteten, scheiterten sofort mit Ergebnis
    1 und schrieben nicht einmal eine Logzeile -- registriert, sichtbar, und
    vollstaendig wirkungslos.

    Eine Datei loest das nicht durch besseres Verschachteln, sondern durch
    gar keins: hier steht genau der Befehl, der laeuft, und er laesst sich
    von Hand ausprobieren, bevor eine Aufgabe ihn uebernimmt.

    Die Logzeile steht VOR dem Skript, damit auch ein Start sichtbar ist, der
    sofort scheitert. Ein Protokoll, das nur vollstaendige Laeufe vermerkt,
    verschweigt genau die Faelle, fuer die es da ist.
    """
    log = LOGS / f"{a.name}.log"
    pfad = LOGS / f"{a.name}.cmd"
    pfad.write_text(
        "@echo off\r\n"
        f'cd /d "{ROOT}"\r\n'
        "setlocal enabledelayedexpansion\r\n"
        "set VERSUCHE=0\r\n"
        # Vorbelegt, damit die erste START-Zeile "(vorher: -)" sagt und nicht
        # eine leere Klammer. Eine Luecke an der Stelle liest sich wie ein
        # verlorener Wert, nicht wie "es gab keinen".
        "set RC=-\r\n"
        "\r\n"
        ":schleife\r\n"
        "set /a VERSUCHE+=1\r\n"
        # Der vorige Rueckgabewert steht auf der START-Zeile, nicht nur auf
        # der ENDE-Zeile -- und das ist ein behobener Fehler.
        #
        # Die ENDE-Zeile erscheint zuverlaessig, wenn der Prozess normal
        # endet, aber NICHT, wenn er abrupt getoetet wird: gemessen zweimal,
        # der Neustart kam korrekt (61 s, "Versuch 2"), die ENDE-Zeile fehlte
        # beide Male. Vermutlich geht der Schreibvorgang verloren, waehrend
        # die Umleitung des sterbenden Kindes noch am Log haengt.
        #
        # Die START-Zeile kommt dagegen immer an -- sie wird geschrieben,
        # wenn nichts mehr am Log haengt. Also traegt sie den Wert mit. Ein
        # Protokoll, das den Grund nur in den leichten Faellen nennt,
        # verschweigt ihn in genau denen, fuer die es da ist.
        f'echo [%date% %time%] START, Versuch !VERSUCHE! '
        f'(vorher: !RC!) >> "{log}"\r\n'
        f'"{PYTHON}" -u "{ROOT / a.skript}" {a.argumente} >> "{log}" 2>&1\r\n'
        # Den Rueckgabewert SOFORT sichern, vor jedem weiteren Befehl.
        #
        # Hier stand ein `echo` zuerst, und das verschluckte ihn: `echo`
        # liefert 0, also meldete die Aufgabe einen erfolgreichen Lauf --
        # egal wie Python gestorben war. Dieselbe Falle wie
        # `pytest ... | tail; echo $?`, wo der Wert von `tail` kommt. Es ist
        # immer der LETZTE Befehl, nie der gemeinte.
        "set RC=!ERRORLEVEL!\r\n"
        f'echo [%date% %time%] ENDE mit !RC! >> "{log}"\r\n'
        f"if !VERSUCHE! GEQ {MAX_VERSUCHE} (\r\n"
        f'  echo [%date% %time%] AUFGEGEBEN nach !VERSUCHE! Versuchen >> "{log}"\r\n'
        "  exit /b !RC!\r\n"
        ")\r\n"
        # `ping` statt `timeout`, und das ist kein Stilgeschmack.
        #
        # `timeout /t` braucht eine Konsole. Unter einer geplanten Aufgabe ist
        # die Eingabe umgeleitet, und dann bricht es sofort ab -- "FEHLER: Die
        # Eingabeumleitung wird nicht unterstuetzt", gemessen in einer
        # Einzelprobe. Der Abstand waere also wirkungslos gewesen und eine
        # Absturzschleife haette ihre zwanzig Versuche in Sekunden verbrannt,
        # statt ueber zwanzig Minuten.
        #
        # `ping -n N 127.0.0.1` wartet N-1 Sekunden und braucht keine Konsole.
        f"ping -n {NEUSTART_ABSTAND_S + 1} 127.0.0.1 > nul\r\n"
        "goto schleife\r\n",
        encoding="utf-8",
    )
    return pfad


def einrichten() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    for a in AUFGABEN:
        datei = startdatei(a)
        befehl = (
            f'$a = New-ScheduledTaskAction -Execute "{datei}" '
            f'-WorkingDirectory "{ROOT}"; '
            f'$t = New-ScheduledTaskTrigger -AtLogOn '
            f'-User "$env:USERDOMAIN\\$env:USERNAME"; '
            # WIEDERHOLUNG, und sie ist der eigentliche Schutz.
            #
            # Am 20.10. starben alle sechs Aufgaben ZWEIMAL gleichzeitig --
            # einmal um 08:01, einmal gegen 13:50. Beide Male steht `^C`
            # woertlich in den Logdateien, also das, was cmd.exe bei einem
            # Ctrl+C ausgibt: von aussen unterbrochen, nicht abgestuerzt. Eine
            # Batch-Schleife ueberlebt das nicht, weil cmd dann "Batchvorgang
            # beenden (J/N)?" fragt und bei umgeleiteter Eingabe EOF liest.
            #
            # WER das Ctrl+C schickt, weiss ich nach zwei Vorfaellen immer noch
            # nicht. Geprueft und ausgeschlossen: Standby (die Maschine hat
            # zwischen 07:59 und jetzt nicht geschlafen), Akku, Zeitlimit,
            # zweite Instanz. `StopOnIdleEnd` war der einzige Verdacht und ist
            # seit heute frueh aus -- es ist trotzdem wieder passiert, der
            # Verdacht ist also widerlegt.
            #
            # Darum hoere ich auf, die Ursache zu suchen, und mache die Anlage
            # davon unabhaengig: ein Wiederholungs-Trigger alle fuenf Minuten,
            # unbegrenzt. Zusammen mit `MultipleInstances = IgnoreNew` heisst
            # das: laeuft die Aufgabe, wird der Start verworfen; ist sie tot,
            # startet sie binnen fuenf Minuten von selbst. Eine Reparatur, die
            # nicht wissen muss, woran der Patient gestorben ist.
            #
            # Der Preis steht im Protokoll: jeder Neustart schreibt eine
            # START-Zeile, also ist eine Luecke in der Stichprobe nachlesbar
            # statt zu erraten.
            # Ein ZWEITER Trigger, und er muss ein ZEIT-Trigger sein.
            #
            # Der erste Versuch haengte die Wiederholung an den Anmelde-Trigger
            # (`$t.Repetition = ...`). Das laesst sich registrieren, man kann es
            # nachlesen -- `Repetition=PT5M` steht brav da -- und es plant
            # NICHTS: `NextRunTime` bleibt leer. Gemessen: Aufgabe um 14:00:49
            # getoetet, fuenf Minuten spaeter immer noch "Ready", kein Lauf.
            # Dieselbe Falle wie `RestartCount` im Oktober: eine Einstellung,
            # die registriert ist, sichtbar ist und nichts tut.
            #
            # Mit einem eigenen Zeit-Trigger fuellt sich `NextRunTime` sofort,
            # und die Reparatur ist nachgemessen statt angenommen: dieselbe
            # Aufgabe getoetet um 14:00:49, von selbst zurueck um 14:07:10.
            #
            # `-RepetitionDuration` wird NICHT gesetzt. `[TimeSpan]::MaxValue`
            # wird zu `P99999999DT23H59M59S`, und die Aufgabenplanung
            # antwortet "Wert ausserhalb des Bereichs" -- "unbegrenzt" heisst
            # dort KEINE Dauer, nicht eine sehr grosse.
            f'$wach = New-ScheduledTaskTrigger -Once '
            f'-At (Get-Date).AddMinutes({WACHINTERVALL_MIN}) '
            f'-RepetitionInterval (New-TimeSpan -Minutes {WACHINTERVALL_MIN}); '
            f'$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries '
            f'-DontStopIfGoingOnBatteries -RestartCount {NEUSTARTS} '
            f'-RestartInterval (New-TimeSpan -Minutes {NEUSTART_ABSTAND_MIN}) '
            f'-ExecutionTimeLimit (New-TimeSpan -Days 0); '
            # Am Morgen des 20.10. starteten alle drei Aufgaben korrekt um
            # 07:59:30 -- drei Sekunden nach dem Aufwachen aus dem Standby --
            # und waren zwei Minuten spaeter alle drei weg, mit Rueckgabewert
            # 0xC000013A. Das ist STATUS_CONTROL_C_EXIT: nicht abgestuerzt,
            # sondern von aussen GESTOPPT. Drei Prozesse gleichzeitig, sauber
            # beendet -- das kann kein Absturz sein.
            #
            # `StopOnIdleEnd` ist der einzige vorhandene Schalter, der genau
            # diese Signatur erzeugt: die Aufgabenplanung stoppt Aufgaben, wenn
            # der Leerlauf endet. Microsoft dokumentiert ihn als wirksam nur bei
            # `RunOnlyIfIdle`, und das steht hier auf false -- BELEGT ist die
            # Ursache also nicht, und der Nachweis fehlt, weil das Protokoll
            # "TaskScheduler/Operational" auf dieser Maschine abgeschaltet ist
            # (Einschalten braucht Adminrechte).
            #
            # Trotzdem abschalten: der Schalter kann nur einen Weg zum Tod
            # entfernen, keinen hinzufuegen. Eine Vermutung, die nichts kostet,
            # darf man ausraeumen -- man darf sie nur nicht fuer bewiesen
            # erklaeren.
            f'$s.IdleSettings.StopOnIdleEnd = $false; '
            f'Register-ScheduledTask -TaskName "{a.name}" -Action $a '
            f'-Trigger @($t, $wach) -Settings $s -Force | Out-Null; '
            f'"eingerichtet: {a.name}"'
        )
        erg = _ps(befehl)
        print(f"  {erg.stdout.strip() or erg.stderr.strip()[:200]}")
        if erg.returncode != 0:
            print(f"  FEHLER bei {a.name}: {erg.stderr.strip()[:300]}")
            return 1

    print(f"\n  Logs liegen unter {LOGS}")
    print("  Sie starten bei der naechsten Anmeldung. Jetzt sofort:")
    print("    python scripts/dauerbetrieb.py --jetzt")
    print("\n  WAS DAS AM VERHALTEN AENDERT, und es gehoert dazu gewusst:")
    print("  Ein Neustart nach einem Absturz ist eine Verhaltensaenderung.")
    print("  Ein fehlgeschlagener Zyklus ist eine ausgelassene Entscheidung,")
    print("  also aendert ein Neustart, welche Trades ueberhaupt existieren --")
    print("  und die Laufsignatur zeichnet das nicht auf. Darum schreibt jeder")
    print("  Start eine Zeile ins Log; eine Luecke in der Stichprobe ist dort")
    print("  nachlesbar statt zu erraten.")
    return 0


def entfernen() -> int:
    for a in AUFGABEN:
        erg = _ps(
            f'if (Get-ScheduledTask -TaskName "{a.name}" '
            f'-ErrorAction SilentlyContinue) {{ '
            f'Unregister-ScheduledTask -TaskName "{a.name}" -Confirm:$false; '
            f'"entfernt: {a.name}" }} else {{ "war nicht da: {a.name}" }}'
        )
        print(f"  {erg.stdout.strip() or erg.stderr.strip()[:200]}")
    print("\n  Laufende Prozesse bleiben laufen -- entfernt ist nur der Autostart.")
    return 0


def status() -> int:
    print(f"{'Aufgabe':28s} {'Zustand':12s} {'letzter Lauf':20s} {'Ergebnis':>10s}")
    print("-" * 74)
    for a in AUFGABEN:
        erg = _ps(
            f'$t = Get-ScheduledTask -TaskName "{a.name}" '
            f'-ErrorAction SilentlyContinue; '
            f'if ($t) {{ $i = $t | Get-ScheduledTaskInfo; '
            f'"$($t.State)|$($i.LastRunTime)|$($i.LastTaskResult)" }} '
            f'else {{ "FEHLT||" }}'
        )
        # Drei Felder, mit Fuellwerten aufgefuellt: eine fehlende Aufgabe
        # liefert weniger, und ein IndexError waere hier die unfreundlichste
        # aller Antworten auf "laeuft es?".
        teile = (*(erg.stdout.strip() or "FEHLT").split("|"), "", "")
        zustand, lauf, ergebnis = teile[0] or "?", teile[1][:19] or "nie", teile[2]
        print(f"{a.name:28s} {zustand:12s} {lauf:20s} {ergebnis:>10s}")
        print(f"{'':28s} {a.zweck}")

    print(f"\nLogs: {LOGS}")
    if LOGS.exists():
        for p in sorted(LOGS.glob("*.log")):
            print(f"  {p.name:34s} {p.stat().st_size/1024:8.1f} kB")
    return 0


def jetzt() -> int:
    """Die Aufgaben sofort starten, statt auf die naechste Anmeldung zu warten.

    Doppelstarts sind unbedenklich: Haendler und Dashboards halten je eine
    Einzelinstanz-Sperre (`papertrade`, und der Port selbst), ein zweiter
    Lauf lehnt also ab statt die Anfragerate zu verdoppeln. Genau das ist am
    07.10.2026 einmal passiert und hat 58 fehlgeschlagene Zyklen erzeugt,
    ohne dass einer der beiden etwas gemerkt haette.
    """
    for a in AUFGABEN:
        erg = _ps(f'Start-ScheduledTask -TaskName "{a.name}"; "gestartet: {a.name}"')
        print(f"  {erg.stdout.strip() or erg.stderr.strip()[:200]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    gruppe = parser.add_mutually_exclusive_group(required=True)
    gruppe.add_argument("--einrichten", action="store_true")
    gruppe.add_argument("--entfernen", action="store_true")
    gruppe.add_argument("--status", action="store_true")
    gruppe.add_argument("--jetzt", action="store_true")
    args = parser.parse_args(argv)

    if not PYTHON.exists():
        print(f"venv nicht gefunden: {PYTHON}", file=sys.stderr)
        return 2

    if args.einrichten:
        return einrichten()
    if args.entfernen:
        return entfernen()
    if args.jetzt:
        return jetzt()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
