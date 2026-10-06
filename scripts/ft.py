"""Run Freqtrade with this project's full config set, every time.

    python scripts/ft.py list-strategies
    python scripts/ft.py download-data --pairs BTC/USDT --timeframes 5m 1h --timerange 20250201-
    python scripts/ft.py backtesting --strategy BaselineTrend --timerange 20250601-20261001
    python scripts/ft.py --measure backtesting --strategy BaselineTrend
    python scripts/ft.py --freqai backtesting --strategy FreqaiCostFiltered

Freqtrade takes its configuration from however many `-c` files are passed and
merges them in order. This project has three: the committed base, the FreqAI
overlay, and the gitignored secrets. Forgetting one does not produce an
obvious failure -- omitting the secrets file makes the API server's schema
reject an empty `jwt_secret_key`, and the download aborts before fetching a
single candle.

That already happened here. The command was backgrounded, the shell reported
exit code 0 because the exit code belonged to the `tail` at the end of the
pipeline, and the notification said "completed". Nothing had been downloaded.
Only looking at the empty data directory revealed it.

So this wrapper exists to make the config set impossible to get wrong, and it
checks the exit code itself rather than leaving that to whatever a pipeline
reports.

**Why not an alias or a shell function.** Both live in one shell's memory and
neither survives the detached restart the order asks for. A script in the
repository is the version that still works tomorrow.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FT_DIR = ROOT / "freqtrade"
USER_DIR = FT_DIR / "user_data"
BINARY = FT_DIR / ".venv" / "Scripts" / "freqtrade.exe"
BINARY_POSIX = FT_DIR / ".venv" / "bin" / "freqtrade"

BASE = USER_DIR / "config.base.json"
FREQAI = USER_DIR / "config.freqai.json"
LOCAL = USER_DIR / "config.local.json"
MEASURE = USER_DIR / "config.measure.json"


def binary() -> Path:
    """The installed Freqtrade, whichever layout the venv has.

    Windows puts console scripts in `Scripts/`, POSIX in `bin/`. The order
    asks for a documented Linux installation later, so this resolves both
    rather than hard-coding the one that happens to be here.
    """
    if BINARY.exists():
        return BINARY
    if BINARY_POSIX.exists():
        return BINARY_POSIX
    raise SystemExit(
        f"Freqtrade ist nicht installiert.\n"
        f"Erwartet: {BINARY}\n"
        f"Einrichten: python -m venv freqtrade/.venv && "
        f"freqtrade/.venv/Scripts/python -m pip install 'freqtrade[freqai]==2026.9'"
    )


def configs(*, freqai: bool, measure: bool = False) -> list[str]:
    """The `-c` chain, in merge order, with every file checked to exist.

    Checked rather than assumed: a missing secrets file is the failure this
    whole module exists to prevent, and discovering it here names the fix
    instead of surfacing a schema error about `minLength: 32`.

    The measurement overlay goes **last** so it wins. Freqtrade merges in the
    order the files are given, so an overlay placed anywhere else is silently
    overridden by the base -- which looks exactly like the overlay not being
    read at all, and would have left the run still going broke halfway.
    """
    chain = [BASE, FREQAI, LOCAL] if freqai else [BASE, LOCAL]
    if measure:
        chain = [*chain, MEASURE]
    missing = [p for p in chain if not p.exists()]
    if missing:
        names = ", ".join(p.name for p in missing)
        hint = (
            "\nFehlt config.local.json? -> python scripts/freqtrade_setup.py"
            if LOCAL in missing
            else ""
        )
        raise SystemExit(f"Konfiguration fehlt: {names}{hint}")

    out: list[str] = []
    for path in chain:
        out += ["-c", str(path)]
    return out


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        "--freqai",
        action="store_true",
        help="Include the FreqAI overlay. Off by default, so a baseline run cannot pick it up.",
    )
    parser.add_argument(
        "--measure",
        action="store_true",
        help="Wallet large enough that the account cannot run out. For measuring "
        "entries over a whole window rather than up to the point of ruin.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the command instead of running it.",
    )
    parser.add_argument("-h", "--help", action="store_true", help="This text, then Freqtrade's.")
    return parser.parse_known_args()


def main() -> int:
    args, rest = parse_args()
    if args.help or not rest:
        print(__doc__)
        print("Weitere Unterbefehle:")
        rest = ["--help"]

    cmd = [
        str(binary()),
        *rest,
        *configs(freqai=args.freqai, measure=args.measure),
        "--userdir",
        str(USER_DIR),
    ]

    if args.show:
        print(" ".join(cmd))
        return 0

    # No shell, and the argument list is passed through as a list: a pair name
    # containing a semicolon is an argument, never a second command.
    completed = subprocess.run(cmd, cwd=FT_DIR, check=False)
    if completed.returncode != 0:
        print(f"\nFreqtrade endete mit Code {completed.returncode}.", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
