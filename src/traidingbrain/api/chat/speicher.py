"""Verlauf und Pruefkarten des Chats in einer eigenen sqlite-Datei."""
from __future__ import annotations

import contextlib
import secrets
import sqlite3
from pathlib import Path
from typing import Literal

from traidingbrain.api.chat.modelle import Urteil, Vorschlag


class ChatSpeicher:
    """Nachrichten und Pruefkarten; jede Operation oeffnet die Datei neu."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS nachrichten ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
                "rolle TEXT NOT NULL, text TEXT NOT NULL, karte_id TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS karten ("
                "id TEXT PRIMARY KEY, vorschlag TEXT NOT NULL, urteil TEXT NOT NULL, "
                "preis REAL, laeuft_ab_ts INTEGER NOT NULL, "
                "ausgefuehrt_ts INTEGER, order_id TEXT)"
            )

    @contextlib.contextmanager
    def _db(self):
        with contextlib.closing(sqlite3.connect(self._path, timeout=10)) as db:
            with db:  # Commit bzw. Rollback am Ende
                yield db

    def nachricht(
        self,
        rolle: Literal["nutzer", "bot"],
        text: str,
        *,
        ts: int,
        karte_id: str | None = None,
    ) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO nachrichten (ts, rolle, text, karte_id) VALUES (?, ?, ?, ?)",
                (ts, rolle, text, karte_id),
            )

    def verlauf(self, limit: int = 50) -> list[dict]:
        """Die letzten `limit` Nachrichten, aelteste zuerst."""
        with self._db() as db:
            zeilen = db.execute(
                "SELECT ts, rolle, text, karte_id FROM nachrichten "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"ts": ts, "rolle": rolle, "text": text, "karte_id": karte_id}
            for ts, rolle, text, karte_id in reversed(zeilen)
        ]

    def karte_anlegen(
        self, vorschlag: Vorschlag, urteil: Urteil, *, ts: int, ttl_s: int
    ) -> str:
        karte_id = secrets.token_hex(6)
        with self._db() as db:
            db.execute(
                "INSERT INTO karten (id, vorschlag, urteil, preis, laeuft_ab_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    karte_id,
                    vorschlag.model_dump_json(),
                    urteil.model_dump_json(),
                    urteil.preis,
                    ts + ttl_s * 1000,
                ),
            )
        return karte_id

    def karte(self, karte_id: str) -> dict | None:
        with self._db() as db:
            z = db.execute(
                "SELECT vorschlag, urteil, preis, laeuft_ab_ts, ausgefuehrt_ts, order_id "
                "FROM karten WHERE id = ?",
                (karte_id,),
            ).fetchone()
        if z is None:
            return None
        return {
            "vorschlag": Vorschlag.model_validate_json(z[0]),
            "urteil": Urteil.model_validate_json(z[1]),
            "preis": z[2],
            "laeuft_ab_ts": z[3],
            "ausgefuehrt_ts": z[4],
            "order_id": z[5],
        }

    def als_ausgefuehrt(self, karte_id: str, order_id: str, *, ts: int) -> bool:
        """Markiert die Karte atomar; nur der erste Aufruf liefert True."""
        with self._db() as db:
            cur = db.execute(
                "UPDATE karten SET ausgefuehrt_ts = ?, order_id = ? "
                "WHERE id = ? AND ausgefuehrt_ts IS NULL",
                (ts, order_id, karte_id),
            )
            return cur.rowcount == 1
