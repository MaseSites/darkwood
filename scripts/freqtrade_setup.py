"""Generate the local secrets Freqtrade's API server needs, once.

    python scripts/freqtrade_setup.py
    python scripts/freqtrade_setup.py --rotate

`config.base.json` is committed and therefore holds no secrets. The API server
nevertheless refuses to start without a JWT key of at least 32 characters --
its own schema enforces that, which is how this file came to exist rather than
a guess about what might be needed.

So the secrets live in `config.local.json`, which `.gitignore` excludes, and
Freqtrade merges the two at startup (`-c base -c local`). Running this twice is
safe: an existing file is kept unless `--rotate` is passed, because rotating
the key invalidates any token a running dashboard still holds.

**Why not environment variables.** Freqtrade does read `FREQTRADE__*`, and that
would work for a single process started from a shell that has them. It does not
survive the detached restart the order asks for, and a key that only exists in
one shell's environment is a key that silently reverts to missing. A gitignored
file is checkable: either it is on disk or it is not.

The username and password are for the loopback API only. The server binds
127.0.0.1 and the order requires that, so this guards the dashboard against
other processes on this machine, not against the internet -- it is not reachable
from the internet at all.
"""

from __future__ import annotations

import argparse
import json
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "freqtrade" / "user_data" / "config.local.json"

#: Minimum the Freqtrade schema accepts for `jwt_secret_key`. Read off the
#: validation error rather than assumed: `minLength: 32`.
KEY_MIN = 32

#: Bytes of entropy per generated secret. `token_urlsafe` yields about 1.33
#: characters per byte, so 32 bytes comfortably clears the 32-character floor.
ENTROPY_BYTES = 32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Replace existing secrets. Invalidates tokens a running dashboard holds.",
    )
    return parser.parse_args()


def build() -> dict[str, object]:
    return {
        "api_server": {
            "jwt_secret_key": secrets.token_urlsafe(ENTROPY_BYTES),
            "ws_token": secrets.token_urlsafe(ENTROPY_BYTES),
            "username": "traidingbrain",
            "password": secrets.token_urlsafe(ENTROPY_BYTES),
        }
    }


def main() -> int:
    args = parse_args()
    if LOCAL.exists() and not args.rotate:
        print(f"{LOCAL.name} existiert schon. --rotate ersetzt die Schluessel.")
        return 0

    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    payload = build()
    LOCAL.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")

    # Owner-only, so another account on this machine cannot read the key.
    # Windows ignores the group and world bits; this is still correct there and
    # meaningful on the Linux host the order asks us to document for later.
    LOCAL.chmod(stat.S_IRUSR | stat.S_IWUSR)

    key = str(payload["api_server"]["jwt_secret_key"])  # type: ignore[index]
    if len(key) < KEY_MIN:
        print(f"Schluessel zu kurz ({len(key)} < {KEY_MIN}).", file=sys.stderr)
        return 1

    print(f"{LOCAL.name} geschrieben, nur fuer den Besitzer lesbar.")
    print("Nutzer: traidingbrain. Das Passwort steht in der Datei, nicht hier --")
    print("ein Geheimnis, das durch ein Terminal laeuft, steht danach im Verlauf.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
