"""Eine Frage mit Bild an die Claude-CLI.

`brain/subscription.run_cli` schickt Text ueber stdin. Ein Bild passt da nicht
hinein: die CLI nimmt es nur als Inhaltsblock einer Nachricht, und das geht nur
mit `--input-format stream-json`, das wiederum `--output-format stream-json`
verlangt. Die Antwort ist dann eine Zeile je Ereignis; die letzte mit
`"type": "result"` hat genau die Felder der gewohnten JSON-Huelle, und darum
entpackt sie dasselbe `unwrap` -- inklusive der Erkennung eines abgelaufenen
Logins, die dort sitzt.

Alle Schalter, die `run_cli` setzt, gelten hier auch: keine Tools, keine
MCP-Server, keine Einstellungen, keine Sitzung auf der Platte, eine Runde.
"""

from __future__ import annotations

import base64
import json
import subprocess

from traidingbrain.brain.subscription import (
    CALL_TIMEOUT_S,
    SubscriptionUnavailableError,
    _is_auth_failure,
    unwrap,
)


def nachricht(text: str, bilder: list[bytes]) -> str:
    """Die eine Nutzer-Nachricht im stream-json-Format: erst die Bilder, dann der Text."""
    inhalt: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(png).decode("ascii"),
            },
        }
        for png in bilder
    ]
    inhalt.append({"type": "text", "text": text})
    return json.dumps({"type": "user", "message": {"role": "user", "content": inhalt}}) + "\n"


def ergebnis_zeile(stdout: str) -> str:
    """Die letzte `result`-Zeile aus dem Ereignisstrom, oder der Strom selbst."""
    for zeile in reversed(stdout.splitlines()):
        zeile = zeile.strip()
        if not zeile.startswith("{"):
            continue
        try:
            ereignis = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if isinstance(ereignis, dict) and ereignis.get("type") == "result":
            return zeile
    return stdout


def frage_mit_bild(
    text: str,
    bilder: list[bytes],
    *,
    executable: str,
    model: str | None = None,
    system_file: str | None = None,
    workspace: str | None = None,
    env: dict[str, str] | None = None,
    timeout_s: float = CALL_TIMEOUT_S,
) -> tuple[str | None, str | None]:
    """Ein Aufruf der CLI mit Bildern; Rueckgabe wie `run_cli`: (Antwort, Sitzung)."""
    command = [
        executable, "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",  # ohne verweigert die CLI stream-json als Ausgabe
    ]
    if model is not None:
        command += ["--model", model]
    if system_file is not None:
        command += ["--system-prompt-file", system_file]
    command += [
        "--tools", "",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--settings", "{}",
        "--max-turns", "1",
        "--no-session-persistence",
    ]
    try:
        fertig = subprocess.run(
            command,
            input=nachricht(text, bilder),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            cwd=workspace,
            env=env,
            check=False,
        )
    except FileNotFoundError as fehler:
        raise SubscriptionUnavailableError(f"{executable!r} is not on PATH.") from fehler
    except subprocess.TimeoutExpired:
        return None, None
    if fertig.returncode != 0:
        detail = (fertig.stderr or fertig.stdout or "").strip()
        if _is_auth_failure(detail):
            raise SubscriptionUnavailableError(
                f"the CLI is not signed in to a Claude subscription.\n{detail[:400]}"
            )
        return None, None
    return unwrap(ergebnis_zeile(fertig.stdout))
