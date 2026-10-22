"""Verlauf und Pruefkarten des Chats."""
from __future__ import annotations

from traidingbrain.api.chat.modelle import Urteil, Vorschlag
from traidingbrain.api.chat.speicher import ChatSpeicher


def _vorschlag() -> Vorschlag:
    return Vorschlag(symbol="btc", side="long", margin_usd=100.0, leverage=5.0)


def _urteil() -> Urteil:
    return Urteil(angenommen=True, regeln=[], order=None, stop_vom_bot=True, preis=64_000.5)


def test_karte_ueberlebt_neuen_speicher(tmp_path):
    pfad = tmp_path / "chat.sqlite"
    erste = ChatSpeicher(pfad)
    karte_id = erste.karte_anlegen(_vorschlag(), _urteil(), ts=1_000, ttl_s=900)
    assert len(karte_id) == 12
    int(karte_id, 16)

    zweite = ChatSpeicher(pfad)
    karte = zweite.karte(karte_id)
    assert karte == erste.karte(karte_id)
    assert karte["laeuft_ab_ts"] == 1_000 + 900_000
    assert karte["vorschlag"] == _vorschlag()
    assert karte["urteil"] == _urteil()
    assert karte["preis"] == 64_000.5
    assert karte["ausgefuehrt_ts"] is None and karte["order_id"] is None
    assert zweite.karte("gibtsnicht00") is None


def test_nur_einmal_ausfuehrbar(tmp_path):
    pfad = tmp_path / "chat.sqlite"
    speicher = ChatSpeicher(pfad)
    karte_id = speicher.karte_anlegen(_vorschlag(), _urteil(), ts=1, ttl_s=900)
    assert speicher.als_ausgefuehrt(karte_id, "o1", ts=5) is True
    # auch ueber einen frischen Speicher (anderer Prozess) nicht ein zweites Mal
    assert ChatSpeicher(pfad).als_ausgefuehrt(karte_id, "o2", ts=6) is False
    karte = speicher.karte(karte_id)
    assert karte["order_id"] == "o1" and karte["ausgefuehrt_ts"] == 5


def test_verlauf_in_reihenfolge(tmp_path):
    speicher = ChatSpeicher(tmp_path / "chat.sqlite")
    speicher.nachricht("nutzer", "eins", ts=10)
    speicher.nachricht("bot", "zwei", ts=20, karte_id="abc")
    speicher.nachricht("nutzer", "drei", ts=30)
    verlauf = speicher.verlauf()
    assert [m["text"] for m in verlauf] == ["eins", "zwei", "drei"]
    assert verlauf[1] == {"ts": 20, "rolle": "bot", "text": "zwei", "karte_id": "abc"}
    # limit liefert die neuesten, weiter chronologisch
    assert [m["text"] for m in speicher.verlauf(limit=2)] == ["zwei", "drei"]
