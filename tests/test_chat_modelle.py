"""Typen des Chats: Normalisierung und Validierung."""
import pytest
from pydantic import ValidationError

from traidingbrain.api.chat.modelle import Vorschlag


def test_vorschlag_normalisiert_symbol():
    assert Vorschlag(symbol="btc", side="long").symbol == "BTCUSDT"
    assert Vorschlag(symbol="ethusdt", side="short").symbol == "ETHUSDT"
    with pytest.raises(ValidationError):
        Vorschlag(symbol="btc", side="buy")
