"""Copy the Obsidian brain into the repository, commit it, and push it.

    python scripts/sync_gehirn.py
    python scripts/sync_gehirn.py --kein-push

The vault in OneDrive stays the one place where notes are written. `gehirn/`
in the repository is a mirror of it, so a colleague gets the brain with the
same `git pull` that brings the code. The mirror runs one way: an edit made in
`gehirn/` is overwritten by the next sync, so notes are changed in the vault.

Only `gehirn/` is staged and committed. Whatever else is changed or staged in
the working tree stays out of the commit.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = Path.home() / "OneDrive" / "Desktop" / "traidingBrainGehirn"
ZIEL = ROOT / "gehirn"

#: Per-person Obsidian state: open tabs, pane layout, the trash. Mirrored, it
#: would overwrite the colleague's own layout on every pull.
AUSGENOMMEN = shutil.ignore_patterns("workspace*.json", ".trash", ".git")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    # The note names carry emoji, and git's output in the console code page
    # cannot decode them; read it as UTF-8 like git writes it.
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=False,
        encoding="utf-8", errors="replace",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", type=Path, default=VAULT)
    parser.add_argument("--remote", default="darkwood")
    parser.add_argument("--kein-push", action="store_true", help="nur spiegeln und committen")
    args = parser.parse_args()

    if not (args.vault / ".obsidian").is_dir():
        print(f"kein Obsidian-Vault unter {args.vault}")
        return 1

    # Wiping and copying is the whole mirror: a note deleted or renamed in the
    # vault disappears here too, which an incremental copy would miss.
    if ZIEL.exists():
        shutil.rmtree(ZIEL)
    shutil.copytree(args.vault, ZIEL, ignore=AUSGENOMMEN)

    _git("add", "-A", "--", "gehirn")
    if _git("diff", "--cached", "--quiet", "--", "gehirn").returncode == 0:
        print("gehirn/ ist schon auf dem Stand des Vaults")
        return 0

    commit = _git("commit", "-m", "Gehirn: Stand des Obsidian-Vaults", "--", "gehirn")
    if commit.returncode != 0:
        print(commit.stdout + commit.stderr)
        return 1
    print(commit.stdout.splitlines()[0])

    if args.kein_push:
        return 0
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    push = _git("push", args.remote, branch)
    print(push.stderr.strip() or push.stdout.strip())
    return push.returncode


if __name__ == "__main__":
    sys.exit(main())
